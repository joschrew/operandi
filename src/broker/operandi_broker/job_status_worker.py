from json import loads
from logging import getLogger
import signal
from os import getpid, getppid, setsid
from sys import exit

from operandi_utils import reconfigure_all_loggers, get_log_file_path_prefix
from operandi_utils.constants import LOG_LEVEL_WORKER, StateJob, StateWorkspace
from operandi_utils.database import (
    DBHPCSlurmJob,
    DBWorkflowJob,
    DBWorkspace,
    sync_db_initiate_database,
    sync_db_get_hpc_slurm_job,
    sync_db_get_workflow_job,
    sync_db_get_workspace,
    sync_db_update_hpc_slurm_job,
    sync_db_update_workflow_job,
    sync_db_update_workspace
)
from operandi_utils.hpc import HPCExecutor, HPCTransfer
from operandi_utils.rabbitmq import get_connection_consumer


class JobStatusWorker:
    def __init__(self, db_url, rabbitmq_url, queue_name, test_sbatch=False):
        self.log = getLogger(f"operandi_broker.worker[{getpid()}].{queue_name}")
        self.queue_name = queue_name
        self.log_file_path = f"{get_log_file_path_prefix(module_type='worker')}_{queue_name}.log"
        self.test_sbatch = test_sbatch

        self.db_url = db_url
        self.rmq_url = rabbitmq_url
        self.rmq_consumer = None
        self.hpc_executor = None
        self.hpc_io_transfer = None

        # Currently consumed message related parameters
        self.current_message_delivery_tag = None
        self.current_message_job_id = None
        self.has_consumed_message = False

    def run(self):
        try:
            # Source: https://unix.stackexchange.com/questions/18166/what-are-session-leaders-in-ps
            # Make the current process session leader
            setsid()
            # Reconfigure all loggers to the same format
            reconfigure_all_loggers(log_level=LOG_LEVEL_WORKER, log_file_path=self.log_file_path)
            self.log.info(f"Activating signal handler for SIGINT, SIGTERM")
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)

            sync_db_initiate_database(self.db_url)
            self.hpc_executor = HPCExecutor()
            self.log.info("HPC executor connection successful.")
            self.hpc_io_transfer = HPCTransfer()
            self.log.info("HPC transfer connection successful.")

            self.rmq_consumer = get_connection_consumer(rabbitmq_url=self.rmq_url)
            self.log.info(f"RMQConsumer connected")
            self.rmq_consumer.configure_consuming(queue_name=self.queue_name, callback_method=self.__callback)
            self.log.info(f"Configured consuming from queue: {self.queue_name}")
            self.log.info(f"Starting consuming from queue: {self.queue_name}")
            self.rmq_consumer.start_consuming()
        except Exception as e:
            self.log.error(f"The worker failed, reason: {e}")
            raise Exception(f"The worker failed, reason: {e}")

    def __download_results_from_hpc(self, job_id: str, job_dir: str, workspace_id: str, workspace_dir: str) -> None:
        sync_db_update_workspace(find_workspace_id=workspace_id, state=StateWorkspace.TRANSFERRING_FROM_HPC)
        sync_db_update_workflow_job(find_job_id=job_id, job_state=StateJob.TRANSFERRING_FROM_HPC)
        self.hpc_io_transfer.get_and_unpack_slurm_workspace(ocrd_workspace_dir=workspace_dir, workflow_job_dir=job_dir)
        self.log.info(f"Transferred slurm workspace from hpc path")
        # Delete the result dir from the HPC home folder
        # self.hpc_executor.execute_blocking(f"bash -lc 'rm -rf {hpc_slurm_workspace_path}/{workflow_job_id}'")
        sync_db_update_workspace(find_workspace_id=workspace_id, state=StateWorkspace.READY)
        sync_db_update_workflow_job(find_job_id=self.current_message_job_id, job_state=StateJob.SUCCESS)

    def __handle_hpc_and_workflow_states(
        self, hpc_slurm_job_db: DBHPCSlurmJob, workflow_job_db: DBWorkflowJob, workspace_db: DBWorkspace
    ):
        hpc_slurm_job_id = hpc_slurm_job_db.hpc_slurm_job_id
        old_slurm_job_state = hpc_slurm_job_db.hpc_slurm_job_state
        new_slurm_job_state = self.hpc_executor.check_slurm_job_state(slurm_job_id=hpc_slurm_job_id)

        job_id = workflow_job_db.job_id
        job_dir = workflow_job_db.job_dir
        old_job_state = workflow_job_db.job_state

        workspace_id = workspace_db.workspace_id
        workspace_dir = workspace_db.workspace_dir

        # If there has been a change of slurm job state, update it
        if old_slurm_job_state != new_slurm_job_state:
            self.log.debug(
                f"Slurm job: {hpc_slurm_job_id}, old state: {old_slurm_job_state}, new state: {new_slurm_job_state}"
            )
            sync_db_update_hpc_slurm_job(find_workflow_job_id=job_id, hpc_slurm_job_state=new_slurm_job_state)

        # Convert the slurm job state to operandi workflow job state
        new_job_state = StateJob.convert_from_slurm_job(slurm_job_state=new_slurm_job_state)

        # If there has been a change of operandi workflow state, update it
        if old_job_state != new_job_state:
            self.log.debug(f"Workflow job id: {job_id}, old state: {old_job_state}, new state: {new_job_state}")
            if new_job_state == StateJob.SUCCESS:
                self.__download_results_from_hpc(
                    job_id=job_id, job_dir=job_dir, workspace_id=workspace_id, workspace_dir=workspace_dir
                )

        self.log.info(f"Latest slurm job state: {new_slurm_job_state}")
        self.log.info(f"Latest workflow job state: {new_job_state}")

    def __callback(self, ch, method, properties, body):
        self.log.debug(f"ch: {ch}, method: {method}, properties: {properties}, body: {body}")
        self.log.debug(f"Consumed message: {body}")

        self.current_message_delivery_tag = method.delivery_tag
        self.has_consumed_message = True

        # Since the workflow_message is constructed by the Operandi Server,
        # it should not fail here when parsing under normal circumstances.
        try:
            consumed_message = loads(body)
            self.log.info(f"Consumed message: {consumed_message}")
            self.current_message_job_id = consumed_message["job_id"]
        except Exception as error:
            self.log.error(f"Parsing the consumed message has failed: {error}")
            self.__handle_message_failure(interruption=False)
            return

        # Handle database related reads and set the workflow job status to RUNNING
        try:
            workflow_job_db = sync_db_get_workflow_job(self.current_message_job_id)
            workspace_db = sync_db_get_workspace(workflow_job_db.workspace_id)
            hpc_slurm_job_db = sync_db_get_hpc_slurm_job(self.current_message_job_id)
        except RuntimeError as error:
            self.log.error(f"Database run-time error has occurred: {error}")
            self.__handle_message_failure(interruption=False)
            return
        except Exception as error:
            self.log.error(f"Database related error has occurred: {error}")
            self.__handle_message_failure(interruption=False)
            return

        self.__handle_hpc_and_workflow_states(
            hpc_slurm_job_db=hpc_slurm_job_db, workflow_job_db=workflow_job_db, workspace_db=workspace_db
        )

        self.has_consumed_message = False
        self.log.debug(f"Acking delivery tag: {self.current_message_delivery_tag}")
        ch.basic_ack(delivery_tag=method.delivery_tag)

    def __handle_message_failure(self, interruption: bool = False):
        self.has_consumed_message = False

        if interruption:
            # self.log.debug(f"Nacking delivery tag: {self.current_message_delivery_tag}")
            # self.rmq_consumer._channel.basic_nack(delivery_tag=self.current_message_delivery_tag)
            # TODO: Sending ACK for now because it is hard to clean up without a mets workspace backup mechanism
            self.log.debug(f"Interruption Acking delivery tag: {self.current_message_delivery_tag}")
            self.rmq_consumer._channel.basic_ack(delivery_tag=self.current_message_delivery_tag)
            return

        self.log.debug(f"Acking delivery tag: {self.current_message_delivery_tag}")
        self.rmq_consumer._channel.basic_ack(delivery_tag=self.current_message_delivery_tag)

        # Reset the current message related parameters
        self.current_message_delivery_tag = None
        self.current_message_job_id = None

    # TODO: Ideally this method should be wrapped to be able
    #  to pass internal data from the Worker class required for the cleaning
    # The arguments to this method are passed by the caller from the OS
    def signal_handler(self, sig, frame):
        signal_name = signal.Signals(sig).name
        self.log.info(f"{signal_name} received from parent process[{getppid()}].")
        if self.has_consumed_message:
            self.log.info(f"Handling the message failure due to interruption: {signal_name}")
            self.__handle_message_failure(interruption=True)

        # TODO: Disconnect the RMQConsumer properly
        # TODO: Clean the remaining leftovers (if any)
        self.rmq_consumer._channel.close()
        self.rmq_consumer = None
        self.log.info("Exiting gracefully.")
        exit(0)

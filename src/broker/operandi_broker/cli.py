import click
from logging import getLogger
from os import environ
from time import sleep

from operandi_utils import reconfigure_all_loggers, get_log_file_path_prefix
from operandi_utils.validators import (
    DatabaseParamType,
    QueueServerParamType
)
from .broker import ServiceBroker
from operandi_utils.constants import LOG_LEVEL_BROKER
from operandi_utils.rabbitmq.constants import (
    RABBITMQ_QUEUE_HARVESTER,
    RABBITMQ_QUEUE_USERS,
    RABBITMQ_QUEUE_JOB_STATUSES
)


__all__ = ['cli']


@click.group()
@click.version_option()
def cli(**kwargs):  # pylint: disable=unused-argument
    """
    Entry-point of multipurpose CLI for Operandi Broker
    """


@cli.command('start')
@click.option('-q', '--queue',
              default=environ.get("OPERANDI_RABBITMQ_URL"),
              help='The URL of the RabbitMQ Server, format: amqp://username:password@host:port/vhost',
              type=QueueServerParamType())
@click.option('-d', '--database',
              default=environ.get("OPERANDI_DB_URL"),
              help='The URL of the MongoDB, format: mongodb://host:port',
              type=DatabaseParamType())
def start_broker(queue: str, database: str):
    log = getLogger("operandi_broker.cli")
    service_broker = ServiceBroker(db_url=database, rabbitmq_url=queue)

    # A list of queues for which a worker process should be created
    queues = [
        RABBITMQ_QUEUE_HARVESTER,
        RABBITMQ_QUEUE_USERS
    ]
    try:
        for queue_name in queues:
            log.info(f"Creating a worker processes to consume from queue: {queue_name}")
            service_broker.create_worker_process(queue_name=queue_name, status_checker=False)
        log.info(
            f"Creating a status checker worker processes to consume from queue: {RABBITMQ_QUEUE_JOB_STATUSES}")
        service_broker.create_worker_process(queue_name=RABBITMQ_QUEUE_JOB_STATUSES, status_checker=True)
    except Exception as error:
        log.error(f"Error while creating worker processes: {error}")

    log_file_path = f"{get_log_file_path_prefix(module_type='broker')}.log"

    # Reconfigure all loggers to the same format
    reconfigure_all_loggers(log_level=LOG_LEVEL_BROKER, log_file_path=log_file_path)

    try:
        # Sleep the parent process till a signal is invoked
        # Better than sleeping in loop, not tested yet
        # signal.pause()

        # Loop and sleep
        while True:
            sleep(5)
    # TODO: Check this in docker environment
    # This may not work with SSH/Docker, SIGINT may not be caught with KeyboardInterrupt.
    except KeyboardInterrupt:
        log.info(f"SIGINT signal received. Sending SIGINT to worker processes.")
        # Sends SIGINT to workers
        service_broker.kill_workers()
        log.info(f"Closing gracefully in 3 seconds!")
        sleep(3)
        exit(0)
    except Exception as error:
        # This is for logging any other errors
        log.error(f"Unexpected error: {error}")

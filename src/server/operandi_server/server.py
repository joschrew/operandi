import datetime
import logging
from os import environ

from fastapi import FastAPI, status

from operandi_utils import (
    OPERANDI_VERSION,
    reconfigure_all_loggers,
    verify_database_uri,
    verify_and_parse_mq_uri
)
from operandi_utils.database import db_initiate_database
from operandi_utils.rabbitmq import (
    # Requests coming from the
    # Harvester are sent to this queue
    DEFAULT_QUEUE_FOR_HARVESTER,
    # Requests coming from
    # other users are sent to this queue
    DEFAULT_QUEUE_FOR_USERS,
    # Requests for job status polling
    # are sent to this queue
    DEFAULT_QUEUE_FOR_JOB_STATUSES,
    RMQPublisher
)

from operandi_server.authentication import create_user_if_not_available
from operandi_server.constants import LOG_FILE_PATH, LOG_LEVEL
from operandi_server.routers import RouterDiscovery, user, workflow, workspace
from operandi_server.utils import safe_init_logging


class OperandiServer(FastAPI):
    def __init__(self, live_server_url: str, local_server_url: str, db_url: str, rabbitmq_url: str):
        self.log = logging.getLogger(__name__)
        self.live_server_url = live_server_url
        self.local_server_url = local_server_url

        try:
            self.db_url = verify_database_uri(db_url)
            self.log.debug(f'Verified MongoDB URL: {db_url}')
            rmq_data = verify_and_parse_mq_uri(rabbitmq_url)
            self.log.debug(f'Verified RabbitMQ URL: {rabbitmq_url}')
            self.rmq_username = rmq_data['username']
            self.rmq_password = rmq_data['password']
            self.rmq_host = rmq_data['host']
            self.rmq_port = rmq_data['port']
            self.rmq_vhost = rmq_data['vhost']
            self.log.debug(f'Verified RabbitMQ Credentials: {self.rmq_username}:{self.rmq_password}')
            self.log.debug(f'Verified RabbitMQ Server URL: {self.rmq_host}:{self.rmq_port}{self.rmq_vhost}')
        except ValueError as e:
            raise ValueError(e)

        # These are initialized on startup_event of the server
        self.rmq_publisher = None
        self.workflow_manager = None
        self.workspace_manager = None

        live_server_80 = {"url": self.live_server_url, "description": "The URL of the live OPERANDI server."}
        local_server = {"url": self.local_server_url, "description": "The URL of the local OPERANDI server."}
        super().__init__(
            title="OPERANDI Server",
            description="REST API of the OPERANDI",
            version=OPERANDI_VERSION,
            license={
                "name": "Apache 2.0",
                "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
            },
            servers=[live_server_80, local_server],
            on_startup=[self.startup_event],
            on_shutdown=[self.shutdown_event]
        )

        self.router.add_api_route(
            path="/",
            endpoint=self.home,
            methods=["GET"],
            status_code=status.HTTP_200_OK,
            summary="Get information about the server"
        )

    async def startup_event(self):
        self.log.info(f"Operandi local server url: {self.local_server_url}")
        self.log.info(f"Operandi live server url: {self.live_server_url}")

        # TODO: Recheck this again...
        safe_init_logging()

        # Reconfigure all loggers to the same format
        reconfigure_all_loggers(log_level=LOG_LEVEL, log_file_path=LOG_FILE_PATH)

        # Initiate database client
        await db_initiate_database(self.db_url)

        # Insert the default server and harvester credentials to the DB
        await self.insert_default_credentials()

        # Connect the publisher to the RabbitMQ Server
        self.connect_publisher(username=self.rmq_username, password=self.rmq_password, enable_acks=True)

        # Create the message queues (nothing happens if they already exist)
        self.rmq_publisher.create_queue(queue_name=DEFAULT_QUEUE_FOR_HARVESTER)
        self.rmq_publisher.create_queue(queue_name=DEFAULT_QUEUE_FOR_USERS)
        self.rmq_publisher.create_queue(queue_name=DEFAULT_QUEUE_FOR_JOB_STATUSES, auto_delete=True)

        # Include the endpoints of the OCR-D WebAPI
        self.include_webapi_routers()

    async def shutdown_event(self):
        # TODO: Gracefully shutdown and clean things here if needed
        self.log.info(f"The Operandi Server is shutting down.")

    async def home(self):
        message = f"The home page of the {self.title}"
        _time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        json_message = {
            "message": message,
            "time": _time
        }
        return json_message

    def connect_publisher(
            self,
            username: str,
            password: str,
            enable_acks: bool = True
    ) -> None:
        self.log.info(f"Connecting RMQPublisher to RabbitMQ server: "
                      f"{self.rmq_host}:{self.rmq_port}{self.rmq_vhost}")
        self.rmq_publisher = RMQPublisher(
            host=self.rmq_host,
            port=self.rmq_port,
            vhost=self.rmq_vhost,
        )
        self.rmq_publisher.authenticate_and_connect(username=username, password=password)
        if enable_acks:
            self.rmq_publisher.enable_delivery_confirmations()
            self.log.debug(f"Delivery confirmations are enabled")
        else:
            self.log.debug(f"Delivery confirmations are disabled")
        self.log.debug(f"Successfully connected RMQPublisher.")

    def include_webapi_routers(self):
        self.include_router(RouterDiscovery().router)
        self.include_router(user.router)
        self.include_router(workflow.router)
        self.include_router(workspace.router)

    async def insert_default_credentials(self):
        default_admin_user = environ.get("OPERANDI_SERVER_DEFAULT_USERNAME", None)
        default_admin_pass = environ.get("OPERANDI_SERVER_DEFAULT_PASSWORD", None)
        default_harvester_user = environ.get("OPERANDI_HARVESTER_DEFAULT_USERNAME", None)
        default_harvester_pass = environ.get("OPERANDI_HARVESTER_DEFAULT_PASSWORD", None)

        self.log.info(f"Configuring default server auth")
        if default_admin_user and default_admin_pass:
            await create_user_if_not_available(
                username=default_admin_user,
                password=default_admin_pass,
                account_type="administrator",
                approved_user=True
            )
            self.log.info(f"Configured default server auth")

        self.log.info(f"Configuring default harvester auth")
        if default_harvester_user and default_harvester_pass:
            await create_user_if_not_available(
                username=default_harvester_user,
                password=default_harvester_pass,
                account_type="harvester",
                approved_user=True
            )
            self.log.info(f"Configured default harvester auth")

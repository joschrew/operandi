import logging
from typing import Optional

from pika import (
    BasicProperties,
    PlainCredentials
)

from .constants import (
    DEFAULT_EXCHANGER_NAME,
    DEFAULT_ROUTER,
    LOG_FORMAT,
    LOG_LEVEL,
    RABBIT_MQ_HOST as HOST,
    RABBIT_MQ_PORT as PORT,
    RABBIT_MQ_VHOST as VHOST
)
from .connector import RMQConnector


class RMQPublisher(RMQConnector):
    def __init__(self, host: str = HOST, port: int = PORT, vhost: str = VHOST,
                 logger_name: str = None) -> None:
        if logger_name is None:
            logger_name = __name__
        logger = logging.getLogger(logger_name)
        logging.getLogger(logger_name).setLevel(LOG_LEVEL)
        # This may mess up the global logger
        logging.basicConfig(level=logging.WARNING)
        super().__init__(logger=logger, host=host, port=port, vhost=vhost)

        self.message_counter = 0
        self.deliveries = {}
        self.acked_counter = 0
        self.nacked_counter = 0
        self.running = True

    def authenticate_and_connect(self, username: str, password: str) -> None:
        credentials = PlainCredentials(
            username=username,
            password=password,
            erase_on_connect=False  # Delete credentials once connected
        )
        self._connection = RMQConnector.open_blocking_connection(
            host=self._host,
            port=self._port,
            vhost=self._vhost,
            credentials=credentials,
        )
        self._channel = RMQConnector.open_blocking_channel(self._connection)

    def setup_defaults(self) -> None:
        RMQConnector.declare_and_bind_defaults(self._connection, self._channel)

    def create_queue(
            self,
            queue_name: str,
            exchange_name: Optional[str] = None,
            exchange_type: Optional[str] = None,
            passive: bool = False
    ) -> None:
        if exchange_name is None:
            exchange_name = DEFAULT_EXCHANGER_NAME
        if exchange_type is None:
            exchange_type = 'direct'

        RMQConnector.exchange_declare(
            channel=self._channel,
            exchange_name=exchange_name,
            exchange_type=exchange_type
        )
        RMQConnector.queue_declare(
            channel=self._channel,
            queue_name=queue_name,
            passive=passive
        )
        RMQConnector.queue_bind(
            channel=self._channel,
            queue_name=queue_name,
            exchange_name=exchange_name,
            # the routing key matches the queue name
            routing_key=queue_name
        )

    def publish_to_queue(
            self,
            queue_name: str,
            message: bytes,
            exchange_name: Optional[str] = None,
            properties: Optional[BasicProperties] = None
    ) -> None:
        if exchange_name is None:
            exchange_name = DEFAULT_EXCHANGER_NAME
        if properties is None:
            headers = {'OCR-D WebApi Header': 'OCR-D WebApi Value'}
            properties = BasicProperties(
                app_id='webapi-processing-server',
                content_type='application/json',
                headers=headers
            )

        # Note: There is no way to publish to a queue directly.
        # Publishing happens through an exchange agent with
        # a routing key - specified when binding the queue to the exchange
        RMQConnector.basic_publish(
            self._channel,
            exchange_name=exchange_name,
            # The routing key and the queue name must match!
            routing_key=queue_name,
            message_body=message,
            properties=properties
        )

        self.message_counter += 1
        self.deliveries[self.message_counter] = True
        self._logger.info(f'Published message #{self.message_counter}')

    def enable_delivery_confirmations(self) -> None:
        self._logger.debug('Enabling delivery confirmations (Confirm.Select RPC)')
        RMQConnector.confirm_delivery(channel=self._channel)

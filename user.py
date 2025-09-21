import asyncio
import logging
import os
import ssl
import time
from pathlib import Path
from multiprocessing import Queue

import aiohttp

from clients import BaseModelClient
from utils import (
    ErrorLog,
    RequestFailureLog,
    RequestSuccessLog,
    get_timestamp_seconds,
)

logger = logging.getLogger(__name__)


class User:
    """User requests to a model client and sends request info to metrics_queue"""

    def __init__(
        self, model_client: BaseModelClient, metrics_queue: Queue, user_id: int = 0
    ):
        self.metrics_queue = metrics_queue
        self.model_client = model_client
        self.run = True
        self.user_id = user_id
        self.start()
        self._stop_event = asyncio.Event()

    async def stop(self) -> None:
        """Stops the User from sending further requests"""
        self.run = False
        await self._stop_event.wait()  # Wait until user_loop finishes

    def start(self) -> None:
        """Starts the user loop as an asyncio task"""
        asyncio.create_task(self.user_loop())

    async def user_loop(self) -> None:
        """sends request continuously while sending request info to metrics queue"""
        # Configure SSL behavior from environment variable LLM_LOCUST_SSL_CERT
        # - If set to a path (file or directory), use it as custom CA bundle
        # - If set to a falsy/disabled value (e.g., "false", "0", "disabled"), disable verification
        # - Otherwise, use default verification
        connector = None
        ssl_env = os.getenv("LLM_LOCUST_SSL_CERT")
        if ssl_env is not None and ssl_env.strip() != "":
            val = ssl_env.strip()
            disabled_values = {"0", "false", "no", "disable", "disabled", "insecure", "skip", "ignore"}
            if val.lower() in disabled_values:
                logger.warning("SSL certificate verification DISABLED via LLM_LOCUST_SSL_CERT")
                connector = aiohttp.TCPConnector(ssl=False)
            else:
                path = Path(val)
                if path.exists():
                    try:
                        if path.is_file():
                            ctx = ssl.create_default_context(cafile=str(path))
                        else:
                            ctx = ssl.create_default_context()
                            ctx.load_verify_locations(capath=str(path))
                        logger.info("Using custom CA for SSL verification from %s", str(path))
                        connector = aiohttp.TCPConnector(ssl=ctx)
                    except Exception as e:
                        logger.exception("Failed to load SSL certs from %s: %s", str(path), e)
                        connector = None  # fall back to default
                else:
                    logger.warning(
                        "LLM_LOCUST_SSL_CERT is set to '%s' but path does not exist. Using default SSL verification.",
                        val,
                    )
        async with aiohttp.ClientSession(connector=connector) as session:
            while self.run:
                url, headers, data, input_data = self.model_client.get_request_params()
                start_time = time.perf_counter()
                try:
                    async with session.post(
                        url,
                        headers=headers,
                        json=data,
                    ) as response:
                        if response.status != 200:
                            # Request is unsuccessful. collect and continue
                            time_key = get_timestamp_seconds()
                            end_time = time.perf_counter()
                            self.metrics_queue.put(
                                RequestFailureLog(
                                    timestamp=time_key,
                                    start_time=start_time,
                                    end_time=end_time,
                                    status_code=response.status,
                                )
                            )
                            logger.info(
                                "Request failure: Status %s, Text %s",
                                response.status,
                                await response.text(),
                            )
                            continue

                        result_chunks = []
                        token_times = []
                        try:
                            async for data, _ in response.content.iter_chunks():
                                token_times.append(time.perf_counter())
                                result_chunks.append(data)
                        except Exception as e:
                            logger.exception(f"Error in user loop: {e}")
                            self.metrics_queue.put(ErrorLog(error_message=str(e)))

                        # TODO: check, if with high sizes for token_times and result chunks, will serialization for queue.put start blocking?
                        time_key = get_timestamp_seconds()
                        end_time = time.perf_counter()
                        self.metrics_queue.put(
                            RequestSuccessLog(
                                result_chunks=result_chunks,
                                num_input_tokens=input_data["num_input_tokens"],
                                timestamp=time_key,
                                token_times=token_times,
                                start_time=start_time,
                                end_time=end_time,
                                status_code=response.status,
                            )
                        )
                except Exception as e:
                    logger.exception(f"Error in user loop: {e}")
                    self.metrics_queue.put(ErrorLog(error_message=str(e)))
        self._stop_event.set()

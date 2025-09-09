"""
IMPORTACAO DAS LIBS
"""
import os
import asyncio
import httpx
import re
import time
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, RetryError
from dotenv import load_dotenv
from loguru import logger
from dataclasses import dataclass
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime

from logger.DiscordHandler import AsyncDiscordHandler 
from logger.LogConfig import LogConfig

"""
Classe de configuracao onde tudo e iniciado e configurado em eventos padroes de forma asincrona.
"""

load_dotenv()

"""
Classe principal na qual e o executor nele tem o discord send, o que cria a fila e envia os processo etc...
"""

def discord_sink(message):
    global _handler

    if not _handler:
        return
    
    record = message.record

    # Se for um fallback do discord, ele ve pra nao entrar em loop
    if record.get("extra", {}).get("discord_fallback"):
        return

    if record["level"].name in ["ERROR", "CRITICAL", "INFO"]:
        level = record["level"].name
        exc_info = record["exception"]

        stack_trace = None
        if exc_info:
            stack_trace = f"{exc_info.type.__name__}: {exc_info.value}\n{''.join(exc_info.traceback)}"

        try:
            asyncio.create_task(_handler.enqueue_message(str(message), level, stack_trace))
            print(f"📝 Log enfileirado: {level}")
        except RuntimeError:
            try:
                os.makedirs("logs", exist_ok=True)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%")
                fallback_msg = f"{timestamp} | NO_LOOP [{level}] | {str(message)}\n"

                with open("logs/discord_no_loop.log", "a", encoding="utf-8") as f:
                    f.write(fallback_msg)
            except Exception:
                print(f"🔥 CRÍTICO - Não foi possível salvar log: {str(message)}")
    
def create_config_for_environment(environment: str = None) -> LogConfig:
    if not environment:
        environment = os.getenv("ENVIRONMENT", "development")

    if environment.lower() == "production":
        return LogConfig(
            max_queue_size=5000,
            max_retries=5,
            batch_interval=10.0,  # Production: flush mais lento
            max_requests_per_window=30,  # Production: mais conservador
            emergency_cooldown=600.0     # Production: 10 minutos
        )   
    elif environment.lower() == "staging":
        return LogConfig(
            max_queue_size=2000,
            max_retries=3,
            batch_interval=5.0,
            max_requests_per_window=50,
            emergency_cooldown=300.0
        )
    else:  # development
        return LogConfig(
            max_queue_size=1000,
            max_retries=3,
            batch_interval=3.0,  # Development: flush mais rápido para testes
            max_requests_per_window=100,
            emergency_cooldown=60.0
            )

_handler: Optional[AsyncDiscordHandler] = None
_handler_task: Optional[asyncio.Task] = None
_logger_configured = False
_manager_active = False 
def _configure_loguru_only():
    # Configura somente o loguro.abs

    global _logger_configured

    if _logger_configured:
        return

    logger.remove()

    logger.add(
        "logs/app/{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
    )

    logger.add(
        "logs/error/{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message} | {extra}",
        enqueue=True
    )

    logger.add(discord_sink, level="INFO", format="{message}")
    logger.add(discord_sink, level="ERROR", format="{message}")

    _logger_configured = True

@asynccontextmanager
async def logger_manager(config: Optional[LogConfig] =None):
    global _handler, _handler_task, _manager_active

    if _manager_active:
        print("⚠️  Logger manager já ativo - retornando logger existente")
        yield logger
        return

    _manager_active = True

    if not config:
        config = create_config_for_environment()

    if not config.error_webhook:
        print("⚠️  AVISO: WEBHOOK DE ERRO não configurado no .env")
    if not config.info_webhook:
        print("⚠️  AVISO: WEBHOOK DE INFO não configurado no .env")




    #Configura o loguro
    _configure_loguru_only()

    async with AsyncDiscordHandler(config) as handler:
        print("b")
        _handler = handler
        try:
            print("🚀 Sistema de logs iniciado com sucesso")
            yield logger
        finally:
            print("🛑 Parando sistema de logs...")            
            _handler = None
            _manager_active = None

__all__ = ["logger", "logger_manager", "create_config_for_environment", "LogConfig"]
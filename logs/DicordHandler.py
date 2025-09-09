import asyncio
import httpx
import re
import os
import random

from typing import Dict
from datetime import datetime, timedelta
from time import strftime
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, RetryError

#Modulos propios
from LogConfig import LogConfig
from MessageDeduplicator import MessageDeduplicator
from IntelligentRateLimiter import IntelligentRateLimiter
#from ..logs import logger

class AsyncDiscordHandler:
    def __init__(self, config: LogConfig):

        self.config = config

        self.queues: Dict[str, asyncio.Queue] = { # Cria as filas
            'ERROR': asyncio.Queue(maxsize=config.max_queue_size),
            'INFO': asyncio.Queue(maxsize=config.max_queue_size)
        }

        self.webhooks = {
            'ERROR': config.error_webhook, 
            'INFO': config.info_webhook
        }

        self.session = None
        self.running = False
        self.flush_task = None

        self.deduplicator = MessageDeduplicator(config.dedup_window)

        self.rate_limiting = IntelligentRateLimiter(
            config.max_requests_per_window, 
            config.rate_limit_window,
            config.emergency_cooldown
        )
    
    async def __aenter__(self):

        self.session = httpx.AsyncClient(timeout=30.0) # Abre sessao httpx

        self.running = True

        print(f"🚀 Iniciando sistema de logs.")

        self.flush_task = asyncio.create_task(self._periodic_flush())

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
            print("🛑 Parando sistema de logs...")
            await self.stop()

            if self.session: # Fecha sessao httpx
                await self.session.aclose()           
    
    def _sanitize_message(self, message: str) -> str:
        """
        limpa mensagem tirando informacoes importantes como senhas key, etc...
        """
        sanitized = re.sub(
            r'(login|user|token|password|key|secret|senha)[\s=:]+[^\s&]+', 
            r'\1=***',
            message,
            flags=re.IGNORECASE
        )
        return sanitized[:500]

    def _format_stack_trace(self, stack_trace: str) -> str:
            """
            Formata stack trace removendo patch completos
            """

            if not stack_trace:
                return "N/A"

            formatted = re.sub(
                r'/[^/\s]+/([^/\s]+/[^/\s]+)', r'/.../\1',
                stack_trace
            )
            return formatted[:200]
  
    def _split_message(self, content: str, max_length: int = 1900) -> list[str]:
        """
        Divide mensagem em ate 1900 caracteres, tamanho maximo do dc.
        """

        if max_length > 1900: 
            print(f"Tamanho maximo atingido")

        chunks = []
        current_chunk = ""

        for line in content.split('\n'):
            # verifica se a chunk atual ja bateu limite
            if len(current_chunk) + len(line) + 1 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = line
                else:
                    while len(line) > max_length:
                        chunks.append(line[:max_length])
                        line = line[max_length:]
                    current_chunk = line
            else:
                current_chunk += f"\n{line}" if current_chunk else line

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    async def _fallback_to_file(self, payload: dict, queue_type: str):
        """Salva mensagem em caso de erro extremo"""

        try:
            os.makedirs("logs", exist_ok=True)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            content = payload.get('content', str(payload))
            fallback_msg = f"{timestamp} | [{queue_type}] | {content}\n"

            with open("logs/discord_fallback.log", "a", encoding="utf-8") as f:
                f.write(fallback_msg)

            print(f"💾 Fallback salvo com sucesso: {queue_type}")
        except Exception as er:
            print(f"🔥 CRÍTICO - Falha no fallback: {er}")

    async def _handler_overflow(self, queue_type: str, item: dict):
        """
        Lida com lotacao na fila removendo itens mais antigos evitando dela quebrar.
        """
        queue = self.queues[queue_type]
        try:
            old_item = queue.get_nowait()
            queue.task_done()

            os.makedirs("logs", exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%")
            overflow_msg = f"{timestamp} | OVERFLOW [{queue_type} | {old_item}]\n"

            with open("logs/discord_overflow.log", "a", encoding="utf-8") as f:
                f.write(overflow_msg)

            queue.put_nowait(item)
            print(f"Overflow tratado em {queue_type}: item antigo salvo, novo adicionado")
        except asyncio.QueueEmpty:
            queue.put_nowait(item)
        except Exception as er:
            print(f"❌ Erro no tratamento de overflow: {er}")

    async def _send_discord_payload(self, webhook_url: str, payload: dict) -> bool:
        """
        Funcao que envia para o discord os payloads, integrada com rate limite inteligente e somente retorna true or false
        """
        try:
            can_send, wait_time = await self.rate_limiting.can_send(webhook_url)
            if not can_send:
                print(f"Rate limite ativo, aguarde {wait_time:.1f}s")
                return False

            async for attempt in AsyncRetrying( stop=stop_after_attempt(self.config.max_retries), wait=wait_exponential(multiplier=1, min=2, max=10)):
                with attempt:
                    response = await self.session.post(webhook_url, json=payload)
                    if response.status_code == 429:
                        retry_after = response.headers.get('retry-after')
                        if retry_after:
                            await self.rate_limiting.apply_cooldown(webhook_url, retry_after)
                        else:
                            await self.rate_limiting.apply_cooldown(webhook_url)

                        return False

                    response.raise_for_status()

                    await self.rate_limiting.record_request(webhook_url)           

                    return True
        except RetryError:
            print(f"Falha apos {self.config.max_retries} tentativas")
        except Exception as er:
            print(f"Erro no envio discord: {er}")

        return False
            
    async def _flush_queue(self, queue_type: str):
        """
        Processsa todos os itens de uma fila especifica.
        Basicamente e o coracao de toda classe aqui e onde o sistema coleta todas as mensagens aplica deduplicacao, agrupa as mensagem, envia criticas individualmente e divide chunks muito longas
        """

        webhook_url = self.webhooks.get(queue_type)

        if not webhook_url: # Se nao tiver webhook pra essse tipo 
            return
        
        queue = self.queues[queue_type]
        messages = []
        

        # Junta as mensagens em uma lista enquanto a fila nao tiver vazia.
        while not queue.empty():
            try:
                item = queue.get_nowait()
                messages.append(item)
                queue.task_done()
            except asyncio.QueueEmpty:
                pass

        if not messages:
            return # Nao tem nd pra processar

        grouped_messages = [] # Agrupa mensagens normais, info etc...
        critical_messages = [] # Messagens criticas.

        for msg_data in messages:
            message = msg_data['message']
            level = msg_data['level']
            stack_trace = msg_data.get('stack_trace')

            if await self.deduplicator.is_duplicate(message, level):
                print(f" - Mensagem duplicada suprimida: {level}")
                continue

            safe_message = self._sanitize_message(message)

            if level == "CRITICAL":

                payload = {
                    "content": f"@everyone\n**NOVO ERRO CRÍTICO**\n```{safe_message}```"
                }

                if stack_trace:
                    stack_trace = self._format_stack_trace(stack_trace)
                    safe_stack = self._format_stack_trace(stack_trace)
                    payload["embeds"] = [{"title": "Stack Trace", "description": safe_stack}]

                critical_messages.append(payload)
            else:
                timestamp = datetime.now().strftime('%H:%M:%S')
                formatted_msg = f"[{timestamp}] {safe_message}"
                grouped_messages.append(formatted_msg)

            # Envia mensagens criticas separadas
        for payload in critical_messages:
            sucess = await self._send_discord_payload(webhook_url, payload)
            if not sucess:
                await self._fallback_to_file(payload, queue_type)
            await asyncio.sleep(0.1)
        if grouped_messages:
            if queue_type =="INFO":
                content_header = "**ATUALIZACAO DO SISTEMA:**\n```\n"
            else:
                content_header = "**LOGS DE ERRO:**\n```\n"
            
            content_body = "\n".join(grouped_messages)
            content_footer = "\n```"

            chunks = self._split_message(content_body)

            print(f"📦 Enviando {len(grouped_messages)} mensagens em {len(chunks)} chunk(s)")

            for idx, chunk in enumerate(chunks):
                header = content_header if idx == 0 else f"**CONTINUAÇÃO ({idx+1}/{len(chunks)})**\n```\n"

                full_content = header + chunk +  content_footer

                payload = {"content": full_content}
                sucess = await self._send_discord_payload(webhook_url, payload)

                if not sucess:
                    await self._fallback_to_file(payload, queue_type)

                if idx < len(chunks) - 1:
                    await asyncio.sleep(0.2)

    async def _periodic_flush(self):
        """
            Roda em segundo plano e a cada x segundos (batch_interval) processa todas as filas enviado as mensagens para serem agrupadas no discord.
        """
        print(f" - Flush periódico iniciado (intervalo: {self.config.batch_interval}s")

        while self.running:
            try:
                await asyncio.sleep(self.config.batch_interval)

                if not self.running:
                    break

                total_processed = 0
                for queue_type in self.queues:
                    queue_size = self.queues[queue_type].qsize()
                    if queue_size > 0:
                        print(f"🔄 Processando fila {queue_type}: {queue_size} mensagens")
                        await self._flush_queue(queue_type)
                        total_processed += queue_size

                if total_processed > 0:
                    print(f"✅ Flush completo: {total_processed} mensagens processadas")

            except asyncio.CancelledError:
                break
            except Exception as er:
                print(f"❌ Erro no flush periódico: {er}")
                #logger.error(f"Erro no flush periódico: {er}", extra={"discord_fallback": True})
                await asyncio.sleep(1)

    async def enqueue_message(self, message: str, level: str, stack_trace: str = None):
        """
        Adiciona mensagens na fila, determina se a fila correta baseada no level e enfileira mensagens e caso encha utiliza o _handler_overflow pra tirar a carga
        """

        if level in ['ERROR', 'CRITICAL']:
            queue_type = 'ERROR'
        else:
            queue_type = 'INFO'

        queue = self.queues.get(queue_type)

        if not queue:
            print(f"⚠️ Fila não encontrada para tipo: {queue_type}")
            return

        item = {
            "message": message, 
            "level": level,
            "stack_trace": stack_trace, 
            "timestamp": datetime.now().isoformat()
        }

        try:
            queue.put_nowait(item)
            print(f"📝 Mensagem enfileirada: {level} → {queue_type}")
        except asyncio.QueueFull:
            print(f"⚠️ Fila {queue_type} cheia, tratando overflow...")
            await self._handler_overflow(queue_type, item)

    async def stop(self):
        self.running = False
        if self.flush_task:
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        
        print("📤 Processando mensagens restantes...")

        total_remaining = 0

        for queue_type in self.queues:
            queue_size = self.queues[queue_type].qsize()
            if queue_size > 0:
                print(f"   📂 Fila {queue_type}: {queue_size} mensagens")
                total_remaining += queue_size
                await self._flush_queue(queue_type)

            if total_remaining > 0:
                print(f"✅ {total_remaining} mensagens restantes processadas")
            else:
                print("✅ Nenhuma mensagem restante")


if __name__ == "__main__":
    async def stress_test():
        """Teste de carga pesado no sistema"""
        from LogConfig import LogConfig
        import random

        config = LogConfig()
        total_messages = 2000   
        concurrency = 20        #

        async with AsyncDiscordHandler(config) as handler:
            print(f"=== TESTE DE CARGA: {total_messages} mensagens com {concurrency} tarefas ===")

            async def worker(worker_id: int):
                for i in range(total_messages // concurrency):
                    level = random.choice(["INFO", "ERROR", "CRITICAL"])
                    msg = f"[W{worker_id}] Mensagem {i} nível {level}"
                    stack = None
                    if level == "CRITICAL":
                        stack = "Traceback (most recent call last):\n  File 'test.py', line 42\nException: Stress test"
                    await handler.enqueue_message(msg, level, stack)
                    # simula burst com pequenas pausas
                    await asyncio.sleep(random.uniform(0.001, 0.02))

            # dispara os workers
            tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
            await asyncio.gather(*tasks)

            print("⏳ Esperando flush final...")
            await asyncio.sleep(config.batch_interval * 2)

        print("=== TESTE COMPLETO ===")

    asyncio.run(stress_test())

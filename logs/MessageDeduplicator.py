import hashlib
import asyncio

from datetime import datetime, timedelta
from typing import Dict

class MessageDeduplicator:
    """
    Um sistema de Deduplicacao de mensagens utilizando se de hash como base.

    Evita de enviar mensagens duplicadas nas logs no discord dentro de uma janela de tempo.
    funciona criando um hash unico para cada combinacao de mensagem (message + level)
    """

    def __init__(self, window_seconds: float = 30.0):
        # Janela de tempo para considerar uma mensagem duplicada

        self.window_seconds = window_seconds
        self.seen_messages: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()


    def _hash_message(self, message: str, level: str) -> str:
        """
        Cria um hash unico para cada mensagem, combinando level assim ja evita de "info db" ser igual a "error db"
        """

        content = f"{level}:{message}"
        return hashlib.md5(content.encode()).hexdigest()

    async def is_duplicate(self, message: str, level: str) -> bool:
        """
        Verifica usando a funcao _hash_message se ela ja foi duplicada e se estamos dentro da janela de tempo.
        """

        async with self._lock:
            message_hash = self._hash_message(message, level)
            now = datetime.now()

            # vai remover mensagens antigas fora da janela
            custoff = now - timedelta(seconds=self.window_seconds)
            self.seen_messages = {
                h: timestamp for h, timestamp in self.seen_messages.items()
                if timestamp > custoff
            }

            # verifica se a mensagem nao ta duplicada
            if message_hash in self.seen_messages:
                print(f"🔄 Mensagem duplicada detectada: {level}")
                return True
            
            self.seen_messages[message_hash] = now
            return False

if __name__ == "__main__":
    async def teste():
        deduper = MessageDeduplicator(window_seconds=5)

        print(await deduper.this_duplicate("teste", "info"))
        print(await deduper.this_duplicate("teste", "info"))
        print(await deduper.this_duplicate("teste", "error"))
        print(await deduper.this_duplicate("outro teste", "info"))
        
        await asyncio.sleep(6)

        print(await deduper.this_duplicate("teste", "info"))

        asyncio.run(teste())


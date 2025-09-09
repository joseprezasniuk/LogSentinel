import asyncio
import random

from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from time import strftime

class IntelligentRateLimiter:
    """
    Rate limite inteligente com cooldown para webhook
    """
    def __init__(self, max_requests: int = 50, window_seconds: int = 60, emergency_cooldown: float = 300.0):
        """
            max_requests: Máximo de requests por janela
            window_seconds: Tamanho da janela em segundos
            emergency_cooldown: Máximo de cooldown em segundos
        """

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.emergency_cooldown = emergency_cooldown

        self.request_history: Dict[str, List[datetime]] = defaultdict(list) # Guarda o historico de requisao em um dicionario

        self.webhook_cooldowns: Dict[str, datetime] = {} # Guarda quais webhooks estao bloqueadas

        self._lock = asyncio.Lock()

    async def can_send(self, webhook_url: str) -> Tuple[bool, Optional[float]]:
        """
        Verifica se e possivel enviar mensagem em caso de retricao, recebe como argumento a webhook e retorna true or false
        """

        async with self._lock:
            now = datetime.now()

            if webhook_url in self.webhook_cooldowns:
                cooldown_until = self.webhook_cooldowns[webhook_url]
                if now < cooldown_until:
                    wait_seconds = (cooldown_until - now).total_seconds()
                    #print(f"❄️ Webhook em cooldown por mais {wait_seconds:.1f}s")
                    return False, wait_seconds
                else:
                    del self.webhook_cooldowns[webhook_url]
                    #print(f"✅ Cooldown expirado para webhook")

            # Limpa historico antigo pra nao encher a memoria
            cutoff = now - timedelta(seconds=self.window_seconds)
            self.request_history[webhook_url] = [
                req_time for req_time in self.request_history[webhook_url]
                if req_time > cutoff
            ]

            current_request = len(self.request_history[webhook_url])
            if current_request >= self.max_requests:
                oldest_request = min(self.request_history[webhook_url])
                wait_seconds = self.window_seconds - (now - oldest_request).total_seconds()
                wait_seconds = max(1.0, wait_seconds)

                #print(f"⚠️ Rate limit {current_request}/{self.max_requests} requests, Aguarde {wait_seconds}")
                return False, wait_seconds

            #print(f"✅ Rate Limit: {current_request}/{self.max_requests} Requests")
            return True, None

    async def record_request(self, webhook_url: str):
        """
        Registra uma requisicao enviada com sucesso.
        """

        async with self._lock:
            self.request_history[webhook_url].append(datetime.now())
            #print(f"📝 Request regitrada com sucessoo, total na janela: {len(self.request_history[webhook_url])}")

    async def apply_cooldown(self, webhook_url: str, retry_after: Optional[int] = None):
        """
        Aplica cooldown baseado no retry afeter ou usa backoff exponecional
        """

        async with self._lock:
            now = datetime.now()
            
            if retry_after:
                cooldown_seconds = min(retry_after, self.emergency_cooldown)
                print(f"⏰ cooldown aplicado Discord: {cooldown_seconds}s (Retry_afer {retry_after})")
            else:
                # Se nao for passado retry ele calcula com base no historico
                recent_cooldowns = sum(
                    1 for cd_time in self.webhook_cooldowns.values()
                    if now - timedelta(minutes=10) < cd_time
                )
                cooldown_seconds = min(5 * (2 ** recent_cooldowns), self.emergency_cooldown)
                print(f"⏰ Aplicado backoff exponencial: {cooldown_seconds}s, (cooldowns {recent_cooldowns})")

            self.webhook_cooldowns[webhook_url] = now + timedelta(seconds=cooldown_seconds)
            print(f"❄️ Webhook em cooldown ate: {self.webhook_cooldowns[webhook_url].strftime('%H:%M:%S')}")

if __name__ == "__main__":
    async def main():
        limiter = IntelligentRateLimiter(max_requests=10, window_seconds=5, emergency_cooldown=30)

        webhook_fake = "https://discordapp.com/api/webhooks/fake" # Nao funciona so pra testar msm
        
        for i in range(1, 500):
            can, wait = await limiter.can_send(webhook_fake)
            if can:
                print(f"Request liberada {i}")
                await limiter.record_request(webhook_fake)
            else:
                print(f"Request bloqueada {i}, espera {wait:.2f}s")
                if wait > 5:
                    await limiter.aplly_cooldown(webhook_url, retry_after=int(wait))
                await asyncio.sleep(wait)

            await asyncio.sleep(random.uniform(0.01, 0.2))
    
    asyncio.run(main())
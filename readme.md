# Discord Logging System

## 📋 Descrição do Sistema

Este sistema é uma ferramenta avançada de logging assíncrono que utiliza o Discord como central de notificações. Desenvolvido especificamente para unificar avisos e facilitar a leitura de logs e erros em projetos menores como agentes de IA, APIs e aplicações Python em geral.

### ✨ Características Principais

- **Sistema Assíncrono:** Processamento não-bloqueante de logs com filas dedicadas
- **Integration Discord:** Envio automático via webhooks com formatação otimizada
- **Rate Limiting Inteligente:** Controle automático de frequência para evitar bloqueios
- **Deduplicação:** Previne spam de mensagens idênticas
- **Fallback Robusto:** Salvamento em arquivos quando Discord está indisponível
- **Configuração Flexível:** Diferentes perfis para desenvolvimento, staging e produção
- **Segurança:** Sanitização automática de dados sensíveis (senhas, tokens, etc.)

## 🏗️ Estrutura do Projeto

```
📁 logger/
├── 📄 logs.py                    # Módulo principal e configuração do loguru
├── 📄 DiscordHandler.py          # Handler principal para Discord
├── 📄 IntelligentRateLimiter.py  # Sistema de rate limiting
├── 📄 LogConfig.py              # Configurações e variáveis de ambiente
└── 📄 MessageDeduplicator.py    # Sistema anti-duplicação
```

## 🔧 Dependências e Pré-requisitos

### Versão Python
- **Python 3.8+** (requerido para sintaxe async/await avançada)

### Bibliotecas Necessárias
```bash
pip install loguru httpx tenacity python-dotenv
```

### Dependências Detalhadas
- `loguru`: Sistema de logging avançado
- `httpx`: Cliente HTTP assíncrono para webhooks
- `tenacity`: Retry automático com backoff exponencial  
- `python-dotenv`: Carregamento de variáveis de ambiente
- `asyncio`: Programação assíncrona (built-in Python 3.8+)

## 📚 Documentação Detalhada dos Módulos

### 1. `logs.py` - Módulo Principal

#### **Função `discord_sink(message)`**
- **Objetivo:** Captura mensagens do loguru e as envia para o sistema Discord
- **Parâmetros:** `message` - Objeto de mensagem do loguru
- **Comportamento:** 
  - Filtra apenas níveis ERROR, CRITICAL e INFO
  - Previne loops infinitos com flag `discord_fallback`
  - Extrai stack traces quando disponíveis
  - Enfileira mensagens de forma assíncrona

#### **Função `create_config_for_environment(environment)`**
- **Objetivo:** Cria configurações otimizadas por ambiente
- **Parâmetros:** `environment` - "production", "staging" ou "development"
- **Retorno:** Objeto `LogConfig` configurado
- **Configurações por Ambiente:**
  - **Production:** Queue 5000, retry 5x, flush 10s, 30 req/min
  - **Staging:** Queue 2000, retry 3x, flush 5s, 50 req/min  
  - **Development:** Queue 1000, retry 3x, flush 3s, 100 req/min

#### **Context Manager `logger_manager(config)`**
- **Objetivo:** Gerencia ciclo de vida completo do sistema de logs
- **Parâmetros:** `config` - Configuração opcional (usa padrão se None)
- **Uso:**
```python
async with logger_manager() as log:
    log.info("Sistema iniciado!")
    log.error("Algo deu errado", extra={"user_id": 123})
```

### 2. `DiscordHandler.py` - Handler Principal

#### **Classe `AsyncDiscordHandler`**

##### **Método `__init__(config: LogConfig)`**
- **Objetivo:** Inicializa handler com configurações
- **Componentes Criados:**
  - Filas separadas para ERROR/CRITICAL e INFO
  - Mapeamento de webhooks por tipo
  - Instâncias de deduplicador e rate limiter

##### **Método `enqueue_message(message, level, stack_trace)`**
- **Objetivo:** Adiciona mensagem na fila apropriada
- **Parâmetros:**
  - `message`: Conteúdo da mensagem
  - `level`: INFO, ERROR ou CRITICAL
  - `stack_trace`: Stack trace opcional para erros
- **Comportamento:** 
  - Determina fila baseada no nível
  - Trata overflow com `_handler_overflow`
  - Adiciona timestamp automático

##### **Método `_flush_queue(queue_type)`**
- **Objetivo:** Processa e envia todas mensagens de uma fila
- **Fluxo de Processamento:**
  1. Coleta todas mensagens da fila
  2. Aplica deduplicação
  3. Agrupa mensagens normais, separa críticas
  4. Envia críticas individualmente com `@everyone`
  5. Agrupa e divide mensagens longas em chunks
  6. Aplica rate limiting e retry automático

##### **Método `_split_message(content, max_length=1900)`**
- **Objetivo:** Divide mensagens longas para limites do Discord
- **Retorno:** Lista de strings com máximo 1900 caracteres cada
- **Algoritmo:** Preserva quebras de linha quando possível

##### **Método `_sanitize_message(message)`**
- **Objetivo:** Remove informações sensíveis das mensagens
- **Padrões Removidos:** login, user, token, password, key, secret, senha
- **Limite:** Trunca mensagens em 500 caracteres

### 3. `IntelligentRateLimiter.py` - Rate Limiting

#### **Classe `IntelligentRateLimiter`**

##### **Método `can_send(webhook_url)`**
- **Objetivo:** Verifica se é possível enviar mensagem
- **Retorno:** `(bool, Optional[float])` - (pode_enviar, tempo_espera)
- **Algoritmo:**
  1. Verifica cooldowns ativos
  2. Limpa histórico antigo
  3. Conta requests na janela atual
  4. Calcula tempo de espera se necessário

##### **Método `apply_cooldown(webhook_url, retry_after)`**
- **Objetivo:** Aplica cooldown baseado em resposta do Discord
- **Estratégias:**
  - **Com retry_after:** Usa valor fornecido pelo Discord
  - **Sem retry_after:** Backoff exponencial baseado em histórico
- **Limite:** Nunca excede `emergency_cooldown`

### 4. `LogConfig.py` - Configurações

#### **Dataclass `LogConfig`**
- **Objetivo:** Centraliza todas configurações do sistema
- **Fonte:** Variáveis de ambiente com fallbacks padrão
- **Configurações Principais:**
  - `error_webhook`/`info_webhook`: URLs dos webhooks
  - `max_queue_size`: Tamanho máximo das filas
  - `batch_interval`: Intervalo entre flushes
  - `max_requests_per_window`: Limite de requests por janela
  - `dedup_window`: Janela para deduplicação

### 5. `MessageDeduplicator.py` - Anti-Duplicação

#### **Classe `MessageDeduplicator`**

##### **Método `is_duplicate(message, level)`**
- **Objetivo:** Detecta mensagens duplicadas
- **Algoritmo:**
  1. Cria hash MD5 de `level:message`
  2. Remove entradas antigas da janela
  3. Verifica se hash já existe
  4. Registra nova mensagem se única
- **Retorno:** `bool` - True se duplicada

## 🚀 Tutorial de Configuração e Execução

### 1. Instalação

```bash
# Clone ou baixe os arquivos
git clone <seu-repositorio>
cd discord-logging-system

# Instale dependências
pip install loguru httpx tenacity python-dotenv
```

### 2. Configuração de Ambiente

Crie arquivo `.env` na raiz do projeto:

```env
# Webhooks do Discord (obrigatório)
ERROR_HOOK=https://discord.com/api/webhooks/ID_ERRO/TOKEN_ERRO
INFO_HOOK=https://discord.com/api/webhooks/ID_INFO/TOKEN_INFO

# Configurações opcionais
ENVIRONMENT=development
MAX_QUEUE_SIZE=1000
BATCH_INTERVAL=3.0
MAX_RETRIES=3
RATE_LIMIT_WINDOW=60
EMERGENCY_COOLDOWN=300.0
DEDUP_WINDOW=30.0
```

### 3. Criando Webhooks no Discord

1. Acesse seu servidor Discord
2. Vá em Configurações do Canal → Integrações
3. Clique em "Criar Webhook"
4. Copie a URL e adicione no `.env`

### 4. Uso Básico

```python
import asyncio
from logger.logs import logger_manager

async def main():
    async with logger_manager() as log:
        # Logs básicos
        log.info("Aplicação iniciada")
        log.warning("Atenção: limite quase atingido")
        log.error("Erro de conexão com banco")
        
        # Log crítico (envia @everyone)
        log.critical("Sistema fora do ar!")
        
        # Com dados extras
        log.error("Falha no login", extra={
            "user_id": 123,
            "ip": "192.168.1.1"
        })

if __name__ == "__main__":
    asyncio.run(main())
```

### 5. Configuração por Ambiente

```python
from logger.logs import create_config_for_environment, logger_manager

# Produção
config_prod = create_config_for_environment("production")

async with logger_manager(config_prod) as log:
    log.info("Sistema em produção ativo")
```

### 6. Teste Individual dos Módulos

#### Teste do Rate Limiter:
```python
# Execute IntelligentRateLimiter.py diretamente
python IntelligentRateLimiter.py
```

#### Teste do Deduplicador:
```python
# Execute MessageDeduplicator.py diretamente  
python MessageDeduplicator.py
```

#### Teste de Carga do Handler:
```python
# Execute DiscordHandler.py diretamente
python DiscordHandler.py
```

### 7. Troubleshooting Comum

#### ❌ **Erro: "WEBHOOK não configurado"**
**Solução:** Verifique se as variáveis `ERROR_HOOK` e `INFO_HOOK` estão corretas no `.env`

#### ❌ **Mensagens não aparecem no Discord**
**Soluções:**
1. Verifique se o webhook está ativo
2. Confirme se o bot tem permissões no canal
3. Verifique logs de fallback em `logs/discord_fallback.log`

#### ❌ **Rate limit atingido**
**Comportamento:** Sistema entra em cooldown automático e salva em arquivo
**Monitoramento:** Observe mensagens como "Webhook em cooldown por Xs"

#### ❌ **Fila cheia**
**Comportamento:** Sistema remove mensagens antigas e salva em `logs/discord_overflow.log`
**Solução:** Aumente `MAX_QUEUE_SIZE` no `.env`

### 8. Monitoramento

O sistema gera arquivos de log automáticos:

```
📁 logs/
├── 📁 app/           # Logs gerais da aplicação
├── 📁 error/         # Logs de erro detalhados  
├── 📄 discord_fallback.log    # Falhas de envio para Discord
├── 📄 discord_overflow.log    # Mensagens removidas por overflow
└── 📄 discord_no_loop.log     # Logs salvos quando loop não disponível
```

## 📊 Resumo Final

### ✅ Pontos Fortes

1. **Arquitetura Robusta:** Sistema assíncrono bem estruturado com separação clara de responsabilidades
2. **Tolerância a Falhas:** Múltiplos níveis de fallback garantem que nenhum log se perde
3. **Performance:** Rate limiting inteligente evita bloqueios desnecessários
4. **Facilidade de Uso:** Interface simples através do loguru padrão
5. **Configurabilidade:** Adaptável para diferentes ambientes e necessidades
6. **Segurança:** Sanitização automática de dados sensíveis

### 🔧 Pontos para Melhoria

1. **Testes Unitários:** Adicionar suite de testes automatizados
2. **Métricas:** Implementar coleta de métricas sobre performance e falhas
3. **Configuração via Interface:** Dashboard web para configuração dinâmica
4. **Suporte a Mais Canais:** Slack, Telegram, email, etc.
5. **Compressão:** Otimizar mensagens muito longas com compressão

### 🤝 Sugestões para Contribuidores

1. **Mantenha Compatibilidade:** Preserve a interface assíncrona existente
2. **Testes Obrigatórios:** Adicione testes para toda nova funcionalidade
3. **Documentação:** Atualize este README com suas mudanças
4. **Performance:** Profile código novo para evitar bottlenecks
5. **Logs Estruturados:** Use formato JSON para logs complexos

### 📞 Suporte

Para dúvidas ou problemas:
1. Verifique a seção de troubleshooting
2. Analise logs em `logs/`
3. Execute testes individuais dos módulos
4. Abra issue no repositório com logs detalhados

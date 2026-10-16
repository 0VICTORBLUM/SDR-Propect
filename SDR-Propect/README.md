# SDR Prospect — Construcril

Aplicação local em Python para apoiar a prospecção B2B nos segmentos de **drywall/construção a seco** e **impermeabilização**, inicialmente em cidades dos estados de São Paulo e Rio de Janeiro.

## Funcionalidades

- Pesquisa de empresas por cidade e segmento usando OpenStreetMap/Overpass.
- Interface única com abas de pesquisa, planilha e configurações.
- Limite diário de novas empresas e limite por pesquisa, persistidos/aplicados localmente.
- Deduplicação por identificador OSM e por nome/cidade/UF.
- Pontuação heurística e justificativa para priorização.
- Mensagem de abordagem personalizada por segmento.
- Registro de status e observações de follow-up.
- Exportação para Excel e CSV.
- Interface minimalista com cores neutras e destaque vermelho.

## Importante sobre a fonte de dados

Esta versão **não consulta o Google Maps**. A API oficial do Google Maps Platform não oferece garantia de custo zero em todos os usos. Para respeitar o requisito de orçamento gratuito, o MVP utiliza OpenStreetMap/Overpass, sujeito à cobertura de dados, disponibilidade e políticas do serviço público.

A fonte pode não fornecer telefone, site, CNPJ ou contato do comprador. O sistema não inventa esses dados: campos sem evidência permanecem vazios. CNPJ e pessoa responsável pelas compras devem ser verificados separadamente em fontes adequadas antes do contato.

A pesquisa é delimitada a uma cidade por vez. Não faça chamadas em massa ou em alta frequência ao Overpass; respeite os limites do serviço. Atribuição OSM: © OpenStreetMap contributors, ODbL — https://www.openstreetmap.org/copyright.

## Requisitos

- Python 3.10 ou superior (recomendado Python 3.11+).
- Acesso à internet para consultar o Overpass.
- Nenhuma chave de API paga é necessária para a pesquisa padrão.

## Instalação no Windows

1. Instale Python: https://www.python.org/downloads/
2. Extraia ou clone este repositório e abra a pasta no VS Code.
3. No terminal, execute:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

Se a ativação do ambiente virtual for bloqueada pela política do PowerShell, abra o terminal CMD e use:

```bat
.venv\Scripts\activate.bat
```

A aplicação abrirá no navegador, normalmente em `http://localhost:8501`.

## Instalação no macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

## Como usar

1. Abra **Configurações** e escolha o limite diário de novas empresas, estado, cidade e segmento padrão.
2. Em **Nova prospecção**, selecione o estado, digite uma cidade, escolha um dos segmentos e defina o limite de novas empresas naquela pesquisa.
3. Clique em **Pesquisar empresas**. O sistema adicionará apenas novos registros até o limite diário configurado.
4. Abra **Planilha de leads** para filtrar, revisar, atualizar o status e exportar os resultados.
5. Revise cada mensagem e valide a empresa e os dados antes de qualquer contato.

## Configuração do serviço de geocodificação

Antes de utilizar o Nominatim, altere `USER_AGENT` em `app.py` para identificar a aplicação e incluir um contato válido do responsável. Use o serviço com baixa frequência e respeite sua política de uso.

## Dados e privacidade

O banco local fica em `data/sdr_prospect.db`. Esse arquivo é ignorado pelo Git para evitar publicação acidental de dados comerciais. Faça backup local de forma segura se necessário. Antes de usar dados pessoais de contatos, avalie a finalidade, a base legal e as salvaguardas aplicáveis à LGPD.

## Limitações da versão inicial

- A pesquisa depende do que foi mapeado no OpenStreetMap.
- A cidade digitada deve corresponder ao nome usado na base geográfica do OSM.
- A pontuação é uma triagem por palavras-chave e tags, não uma previsão de compra.
- CNPJ e contato do comprador não são enriquecidos automaticamente.
- Não há disparo de WhatsApp nem integração com RD Station nesta versão.
- O serviço Overpass pode estar temporariamente indisponível ou limitar consultas.

## Testes

```bash
python -m unittest discover -s tests
python -m streamlit run SDR-Propect/app.py
python -m streamlit run SDR-Propect/app.py
```

## Próximas evoluções recomendadas

1. Melhorar o catálogo de termos de pesquisa a partir do portfólio real da Construcril.
2. Acrescentar verificação manual de site e CNPJ com registro da fonte e data.
3. Construir serviço de enriquecimento separado, usando apenas fontes e APIs autorizadas.
4. Integrar ao RD Station somente após confirmar permissões e credenciais.
5. Avaliar uma fonte comercial licenciada caso seja necessário mais cobertura que a disponível no OSM.

## Contexto comercial usado nas mensagens

O catálogo Construcril 2026 enviado para o projeto apresenta linhas de massas e bases, incluindo Base Coat Médio, Base Coat Ultrafino e Massa Cimentícia, relevantes para investigar empresas de drywall/construção a seco. O índice também lista linhas de impermeabilizantes como Elastic, Elastic UV, Flex 2000 e Flex Plus. As mensagens são sugestões iniciais e não substituem a validação do vendedor sobre aplicação, disponibilidade e adequação técnica do produto.

Cada lead também recebe um link de pesquisa no Google Maps para facilitar a conferência visual do estabelecimento. Esse link é apenas um atalho de consulta; os dados da busca automática continuam vindo do OpenStreetMap nesta versão.

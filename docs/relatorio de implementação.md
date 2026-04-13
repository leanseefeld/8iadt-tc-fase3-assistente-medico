Relatório de implementação do assistente.
Apresenta o raciocínio da equipe para abordar o problema e desenvolver a solução.

-----
# Interpretação Não-Técnica do Desafio

Para direcionar os trabalhos da equipe e arquitetar a solução, partimos para a criação de um protótipo da interface pela qual o médico irá interagir.

O problema pede uma plataforma que sirva como assistente médico, com um cadastro mínimo de pacientes e exames, além de uma integração com LLM para conversação e auxílio em atendimentos.

O usuário alvo é o médico que presta atendimento e se beneficiaria de consultas facilitadas em linguagem natural a protocolos de atendimento e uma base de conhecimento médico no geral.

A plataforma deve reagir a eventos no sistema que indiquem urgência no atendimento decorrentes de check-in de pacientes em situação grave, resultados anormais de exames ou alterações no quadro do paciente.

Utilizando IA, criamos as seguintes telas em um frontend React com dados simulados:

* **Check-in/Admissão**: é por onde pacientes entram no sistema e podem ser automaticamente analisados pelo assistente. Aqui deverão ser informados dados básicos como idade, sexo, comorbidades, podendo também serem informados sintomas, sinais vitais e medicamentos em uso para um melhor resultado. Aqui são cadastrados ou selecionados pacientes para as demais consultas.
* **Dashboard**: visão geral do paciente, com CID principal, últimos sinais vitais, exames pendentes, alertas e histórico.
* **Chat com Assistente**: principal componente de interação, irá expor a interação entre o médico e o assistente, com perguntas sugeridas, fontes consultadas pelo agente e o fluxo de raciocínio (como chegou na resposta e nas fontes).
* **Fluxo de decisão**: a ideia é mostrar o fluxo de decisão do agente logo após a admissão do paciente, indicando etapas como triagem, consulta de protocolos, checagem de exames pendentes, sugestão de ações e alertas emitidos.
* **Exames**: relação de exames realizados e pendentes para o paciente ativo.
* **Ações sugeridas**: apresenta um resumo do caso, gerado pelo assistente, e uma lista de ações sugeridas - que podem ser aceitas, rejeitadas ou aceitas com modificações. Deve, também, indicar as fontes que justifiquem as sugestões.
* **Alertas**: aqui serão exibidos todos os alertas gerados pelo assistente, para todos os pacientes. Deverá ser possível selecionar rapidamente o paciente para o qual o alerta foi emitido, entender o porquê do alerta e marcar o alerta como resolvido.

![Tela admissão](./assets/Screenshot%202026-04-06%20at%2017.34.47.png)

# Dados para Fine Tuning e RAG

## Protocolos Clínicos

Para o corpus de protocolos clínicos, recorremos a [Comissão Nacional de Incorporação de Tecnologias no Sistema Único de Saúde (**CONITEC**)](https://www.gov.br/conitec/pt-br/assuntos/avaliacao-de-tecnologias-em-saude/protocolos-clinicos-e-diretrizes-terapeuticas#TopoPCDT), que publica uma série de Protocolos Clínicos e Diretrizes Terapêuticas (**PCDT**) orientando atendimentos, diagnósticos e tratamentos na rede pública de saúde do Brasil.
Estes protocolos são disponibilizados em formato PDF e em idioma Português.

Outros documentos auxiliares são disponibilizados nesta mesma fonte para auxiliar em tratamento oncológico e outras condições, mas optamos por começar apenas com uma categoria de documentos para testar a implementação e não sobrecarregar o ambiente de desenvolvimento local - afinal, os documentos precisam ser descarregados pela rede, processados e armazenados.

## Exames e Laudos laboratoriais

Para entender o formato de resultados laboratoriais e preparar o assistente para a sua interpretação, recorremos a base de [Dados COVID Hospital Israelita Albert Einstein](https://repositoriodatasharingfapesp.uspdigital.usp.br/handle/item/98).

Os dados já estão anonimizados, mas ainda é necessário um aceite aos termos de uso para descarregar e utilizar esta base.

Embora os exames desta base tenham sido solicitados no contexto de diagnóstico e acompanhamento de quadros de COVID-19, os exames são de natureza diversa e podem ajudar o modelo a generalizar bem para outras condições.

## Pipeline de extração e preparo de documentos

Foi criado um utilitário em `/llm` para baixar e converter os PCDTs automaticamente. Este utilitário se comporta como um módulo isolado para as diferentes fases da pipeline.
Seus componentes e modo de usar são descritos no em [llm/README.md](../llm/README.md).

### Download dos datasets

```sh
download-pcdt # para os PDFs com os PCDTs da CONITEC/SUS
download-clinical-exams # para baixar ou extrair os exames para COVID do Albert Einstein
```

Estes utilitários carregam os datasets diretamente da internet, salvando para a pasta `llm/data/raw`.

Para os PCDTs, o HTML da página é carregado em Python e seletores CSS (ou operações equivalentes) são usados para selecionar os link do documento e seus títulos (primeiro `<table>` de conteúdo da página).

O dataset COVID requer aceite de termos e por isso um navegador é aberto automaticamente para que o usuário preencha os dados e faça o aceite. Do contrário, o utilitário também pode ser executado com o argumento `--zip caminho/do/dataset.zip` para usar o arquivo zip do dataset previamente baixado.

Para ambos os datasets, um arquivo `.jsonl` é criado em `llm/data/manifests` contendo URL de origem, SHA do arquivo baixado, nome salvo localmente, data de acesso e descrição da fonte (publicação e data).

### Conversão para Markdown

```sh
extract-pcdt-markdown
```

Através deste utilitário, usamos a lib `pymupdf4llm` para gerar conteúdo Markdown a partir dos PCDTs. Cada documento resulta em um `.pages.jsonl` em `llm/data/processed/pcdt` contendo a página original e seu conteúdo convertido para Markdown. Se executado com `--with-combined-md`, gera também um arquivo .md com todas as páginas concatenadas.

Um novo manifesto é gerado (`llm/data/manifests/pcdt_md_extract.jsonl`) para rastrear erros e permitir processar apenas novos documentos.

Nenhum tratamento adicional foi implementado para os documentos. O objetivo é entender como os documentos são gerados antes de implementar melhorias.

### Geração de chunks

```sh
chunk-pcdt
```

A geração de tokens usa `MarkdownHeaderTextSplitter` e `RecursiveCharacterTextSplitter` (quando se excede a estimativa de 800 tokens) para geração de chunks a partir dos arquivos gerados na etapa anterior. Há tratamento para indexar a seção e cabeçalhos prévios onde o conteúdo extraído aparece.

O resultado da execução são arquivos `.jsonl` para cada documento inicial, que são salvos em `llm/data/chunks`, e um novo `manifests/pcdt_chunk_index.jsonl` com um registro para cada documento PCDT.

Um visualizador de chunks foi implementado para facilitar a exploração dos resultados deste processo e realizar ajustes no algoritmo.

```sh
view-pcdt-chunks
```
![Preview do visualizador de chunks](./assets/Screenshot%202026-04-12%20at%2022.07.53.png)

Em primeiro momento, é possível perceber que uma estratégia melhor é necessária para capturar corretamente os cabeçalhos e seções relevantes.
Há também problemas em formatação de tabelas, especialmente quando a tabela é continuada em outra página.

Há conteúdo potencialmente redundante (como página inicial de cada documento, como declaração do órgão regulador - Ministério da Saúde) e referências que talvez não possamos usar adequadamente para fundamentar as respostas pois exigiria identificar suas chamadas no corpus e correlacionar com sua declaração na seção de referências do documento (geralmente ao fim).

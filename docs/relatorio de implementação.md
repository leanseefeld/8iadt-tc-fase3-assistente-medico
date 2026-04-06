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

Foi criado um utilitário em `llm/` para baixar os PCDTs automaticamente

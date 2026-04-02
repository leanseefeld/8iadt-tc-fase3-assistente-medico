# TECH CHALLENGE

O Tech Challenge é o projeto que engloba os conhecimentos obtidos em todas as disciplinas da fase. Esta é uma atividade que, em princípio, deve ser desenvolvida em grupo. É importante atentar-se ao prazo de entrega, uma vez que essa atividade é obrigatória, valendo 90% da nota de todas as disciplinas da fase.

## Desafio

Após o sucesso na automação de análises de exames e textos clínicos, o hospital quer avançar para um nível superior de personalização: criar um **assistente virtual médico**, treinado com os dados próprios do hospital, capaz de auxiliar nas condutas clínicas, responder dúvidas de médicos e sugerir procedimentos com base nos protocolos internos.

Além disso, a ideia é organizar fluxos de decisão automatizados e seguros, onde, por exemplo, ao receber informações sobre um paciente, o sistema possa acionar diferentes etapas, como verificar exames pendentes, sugerir tratamentos e emitir alertas para a equipe médica — tudo isso coordenado com **LangChain**.

## Requisitos obrigatórios

### Entregas técnicas:

#### 1. Fine-tuning de LLM com dados médicos internos

- Realizar o fine-tuning de um modelo LLM (como LLaMA, Falcon ou um outro) utilizando:
  - Protocolos médicos do hospital;
  - Exemplos de perguntas frequentes feitas por médicos;
  - Modelos de laudos, receitas e procedimentos internos.
- Preparar os dados com técnicas de **preprocessing**, anonimização e curadoria.

#### 2. Criação de assistente médico com LangChain

- Utilizar o **LangChain** para:
  - Construir um pipeline que integre a LLM customizada;
  - Realizar consultas em base de dados estruturadas (como prontuários e registros);
  - Contextualizar as respostas da LLM com informações atualizadas do paciente.

#### 3. Segurança e validação

- Definir os limites de atuação do assistente para evitar sugestões impróprias (exemplo: nunca prescrever **diretamente, sem a validação humana**);
- Implementar logging detalhado para rastreamento e auditoria;
- Garantir explainability das respostas da LLM (exemplo: indicar a fonte da informação utilizada na resposta).

#### 4. Organização do código

- Projeto modularizado em Python;
- Instruções completas no README.

### Entregáveis da Fase 3

**Repositório Git:**

- Código-fonte com:
  - Pipeline de fine-tuning;
  - Integração com LangChain;
  - Fluxos do LangGraph.
- Dataset anonimizado ou exemplo de dados sintéticos;
- Relatório técnico detalhado com:
  - Explicação do processo de fine-tuning;
  - Descrição do assistente médico criado;
  - Diagrama do fluxo LangChain;
  - Avaliação do modelo e análise dos resultados.

### Sugestão para Datasets


| Nome do Dataset | Conteúdo                                                       | Link                                                                     |
| --------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| PubMedQA        | Perguntas e respostas clínicas com base em publicações médicas | [https://pubmedqa.github.io/](https://pubmedqa.github.io/)               |
| MedQuAD         | Conjunto de perguntas e respostas sobre saúde                  | [https://github.com/abachaa/MedQuAD](https://github.com/abachaa/MedQuAD) |



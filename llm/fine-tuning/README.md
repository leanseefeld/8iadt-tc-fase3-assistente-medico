Este documento traz um panorama geral do processo de Fine-tuning.
Para uma análise mais detalhada, consulte o [relatório de implementação](../../docs/relatorio%20de%20implementação.md#fine-tuning)

# Fine-tuning

O fine-tuning do modelo usado na entrega foi executado em Google Colab, no ambiente T4.

Para execução do treinamento em dispositivos Apple, foi criado uma versão do treinamento usando `mlx-lm` e `mlx-tune`. 

- Colab: [fine-tuning_colab_assistente.ipynb](./fine-tuning_colab_assistente.ipynb) (avalie esta versão)
- Apple MLX: [fine-tuning_apple-silicon_assistente.ipynb](./fine-tuning_apple-silicon_assistente.ipynb) (desatualizado)

A versão final foi treinada com conversas feitas no próprio assistente já construído, com modelos Llama3.2:3b e Gemma4:e4b.

Foi realizada a quantização de 4bits (Q4_K_M) para otimização de memória e velocidade de inferência.

As conversas são extraídas usando o notebook [export-positive-conversations.ipynb](./export-positive-conversations.ipynb), com o system prompt e mensagem formatadas enviadas para e recuperadas do assistente. Também foram usadas as outras chamadas para LLM, como `rewrite`, `rerank` e `guardrail_rewrite`.

A curadoria das conversas é feita através de feedback do usuário (no caso, os membros desta equipe). Conversas sem avaliação positiva, ou com mensagens que tenham sido reescritas pelo guardrail são descartadas.

Para executar o modelo com Ollama, execute:

```bash
ollama run hf.co/leanseefeld/assistente-medico-llama32-3b-q4km:Q4_K_M
```

Para usar o modelo treinado na aplicação, altere seu `/backend/.env` para incluir:
```
MEDICO_OLLAMA_CHAT_MODEL=hf.co/leanseefeld/assistente-medico-llama32-3b-q4km:Q4_K_M
```

## Resultados

Consulte a seção [Resultados finais](../../docs/relatorio%20de%20implementação.md#resultados-finais)
 do relatório de implementação.

## MedQuAD (descartado)

A versão inicial do modelo foi treinada usando a base MedQuAD, porém foi constatado que modelos locais como gemma4:e4b produziam respostas melhores e mais consistentes do que as avaliadas como excelente no dataset.

O processamento do dataset (reconstrução e tradução) está documentado em [data-prep.ipynb](./data-prep.ipynb), e a última versão do treinamento do modelo usando este dataset está em [](./fine-tuning_apple-silicon_medquad.ipynb).

Como o dataset possuía respostas em formatos inconsistentes por ter sido extraído de FAQs de sites de agências de saúde, as respostas do modelo treinado também foram inconsistentes. Isso foi o que motivou a fazer o treinamento com conversas usando gemma4:e4b e usando o MedQuAD apenas como referência de que perguntas fazer.
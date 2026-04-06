### Visão geral da estrutura do conjunto de dados

O diretório contém três arquivos principais: um dicionário de dados, um arquivo de resultados de exames e um arquivo de dados demográficos dos pacientes.

1. **`EINSTEIN_Dicionario_2.xlsx`**:
   - **Função:** serve como **dicionário de dados** ou referência de esquema. Não contém registros brutos, e sim define *o que* as colunas dos outros arquivos significam, em que formato os dados devem vir (por exemplo, formato de data, valores de código) e como os campos se relacionam.
2. **`EINSTEIN_Pacientes_2.csv`**:
   - **Função:** deve concentrar informações **demográficas dos pacientes**: identificação e contexto de cada indivíduo cujos resultados de laboratório aparecem no conjunto.
   - **Pontos de dados relevantes (esperados):** identificador do paciente (`ID_PACIENTE`), sexo (`IC_SEXO`), ano de nascimento (`AA_NASCIMENTO`) e dados de endereço (país, UF, município, CEP).
3. **`EINSTEIN_Exames_2.csv`**:
   - **Função:** deve conter os **resultados de exames laboratoriais**, ligando cada paciente aos testes realizados.
   - **Pontos de dados relevantes (esperados):** informações do exame, vínculo com `ID_PACIENTE`, analito medido (`DE_ANALITO`), valor do resultado, faixa de referência (`DE_VALOR_REFERENCIA`) e data da coleta (`DT_COLETA`).

**Em resumo:**

- **`EINSTEIN_Pacientes_2.csv`** responde **quem** é o paciente.
- **`EINSTEIN_Exames_2.csv`** responde **quais** exames foram feitos e **quais** foram os resultados.
- **`EINSTEIN_Dicionario_2.xlsx`** explica **como** interpretar os dados dos outros dois arquivos.

### Estrutura do dicionário de dados

O dicionário descreve variáveis do que parece ser dado de exames laboratoriais, relacionando demografia, datas de coleta, detalhes do exame e resultados.

**Campos / entidades centrais:**

- **Identificação do paciente:**
  - `ID_PACIENTE`: identificador único do paciente (correlaciona com `EINSTEIN_Pacientes_2.csv`).
  - `IC_SEXO`: sexo (por exemplo, `F` feminino, `M` masculino).
  - `AA_NASCIMENTO`: ano de nascimento (quatro dígitos ou `AAAA` para anonimização pré-1930).
  - `CD_PAIS`: país de residência (por exemplo, `BR`).
  - `CD_UF`: unidade da federação (dois caracteres, por exemplo `SP`).
  - `CD_MUNICIPIO`: município de residência (nome completo ou quatro caracteres).
  - `CEP`: CEP (cinco primeiros dígitos ou `CCCC` para anonimização).
- **Coleta e detalhes do exame:**
  - `DT_COLETA`: data da coleta da amostra (formato `DD/MM/AAAA`).
  - `DE_ORIGEM`: origem do registro (por exemplo, `LAB` laboratório, `HOSP` hospital).
  - `DE_EXAME`: descrição do exame (por exemplo, `HEMOGRAMA`).
  - `DE_ANALITO`: descrição do analito (por exemplo, `Glicose`, `Ureia`).
  - `DE_RESULTADO`: resultado medido (por exemplo, `HEMATOGRAMA`, `SÓDIO`).
- **Valores e contexto:**
  - `DE_VALOR_REFERENCIA`: faixa de referência do analito (por exemplo, `75 a 99`).
  - `CD_UNIDADE`: unidade de medida (por exemplo, `g/dL`).
  - `CONTEUDO`: conteúdo / carga útil do campo.

---

### Agrupamento por variáveis principais

| Nome da variável         | Descrição                          | Exemplo de conteúdo / formato                             | Observações                       |
| ------------------------ | ---------------------------------- | --------------------------------------------------------- | --------------------------------- |
| **ID_PACIENTE**          | Identificador único do paciente.   | Cadeia alfanumérica.                                      | Chave principal.                  |
| **IC_SEXO**              | Sexo do paciente.                  | `F` ou `M`.                                               | Código de um caractere.           |
| **AA_NASCIMENTO**        | Ano de nascimento.                 | Quatro dígitos (ou `AAAA`).                               | Contexto temporal.                |
| **CD_UF**                | Unidade da federação.              | Dois caracteres (por exemplo, `SP`).                      | Código de estado brasileiro.      |
| **DE_ANALITO**           | Analito específico.                | Texto (por exemplo, `Glicose`).                           | Domínio pode ser limitado.        |
| **DE_RESULTADO**         | Grupo / resultado principal.       | Texto (por exemplo, `HEMATOGRAMA`).                       | Relaciona-se ao tipo de exame.    |
| **DE_VALOR_REFERENCIA**  | Faixa de referência.               | `'Valor Minimo' a 'Valor Máximo'` (por exemplo, `75 a 99`). | Faixa em texto.                   |
| **DT_COLETA**            | Data da coleta.                    | `DD/MM/AAAA`.                                             | Formato de data.                  |

---

### Notas para tratamento dos dados

1. **Separadores:** os campos costumam ser separados pelo caractere pipe (`|`).
2. **Granularidade:** um mesmo exame (`DE_EXAME`) pode ter vários analitos (`DE_ANALITO`) com resultados e faixas correspondentes.
3. **Ligação entre arquivos:** o dicionário referencia pontos que devem aparecer nos CSV `EINSTEIN_Exames_2.csv` e `EINSTEIN_Pacientes_2.csv`.

Em síntese, o dicionário define o esquema e o significado dos dados distribuídos entre o arquivo demográfico e o de resultados de laboratório.

# Guia de uso

O AfterDrive Intelligence busca notícias do setor de autopeças nos sites que você escolher, filtra com inteligência artificial e escreve com elas posts B2B para o blog da AfterDrive by Alephee. Você revisa cada post, corrige se for preciso e publica no HubSpot.

Este guia explica cada parte da aplicação. Para um tour rápido na tela: **Ajuda → Repetir o tutorial**, no rodapé da barra lateral.

> O idioma da interface (Español, Português, English) muda nos botões **ES / PT / EN** no canto superior direito ou no primeiro passo do tutorial. Ele muda só a interface: o idioma de cada post depende da região (veja **Criar post**). A documentação técnica está em espanhol.

## Como funciona, em três passos

1. **Juntar notícias.** Todos os dias, no horário que você agendar, o sistema verifica suas fontes, salva as notícias novas do setor e descarta as que não são (por exemplo, venda de carros 0 km ou seguros). De cada notícia salva uma ficha com os dados principais.
2. **Escrever o post.** Com as notícias mais úteis e recentes, o sistema monta um plano, escreve o post, verifica que cada número e cada empresa venham das notícias, revisa estilo e SEO e, se encontrar um problema, corrige. Como imagem de destaque usa a foto de uma dessas notícias.
3. **Revisar e publicar.** O post fica no **Histórico** como "Para revisar". Você lê, avalia, edita se quiser, aprova e publica no blog.

## Início

É o seu conteúdo de hoje:

- **Posts para revisar**, notícias prontas para usar, fontes ativas e quando sai o próximo post automático. Toque em qualquer um para ir direto.
- **Último post** gerado, com um botão para lê-lo.
- **Para revisar**: os posts que aguardam sua leitura.
- **Atividade do sistema**: o que ele está fazendo agora.

## Criar post

Para escrever um post quando quiser, sem esperar o automático.

| Opção | Para que serve |
|---|---|
| **Categorias** | O tema do post. Escolha uma ou mais |
| **Tom** | Comercial, analítico-técnico, jornalístico, divulgativo ou executivo |
| **Tamanho aproximado** | Curto (500 a 700 palavras), médio (700 a 1000) ou longo (1000 a 1400) |
| **Tema específico** | Opcional, para delimitar ("dropshipping na Argentina") |
| **Link de destino** | Um link para onde o post deve levar o leitor |
| **Regiões** (em "Mais opções") | O mercado e o idioma. Com Brasil o post é escrito em português; sem região, em espanhol rio-platense |
| **Clientes** (em "Mais opções") | Empresas que o post pode citar como casos reais |

- **Gerar post** escreve com o que está na tela. Leva alguns minutos; você pode continuar usando a aplicação enquanto isso.
- **Salvar alterações** deixa esta configuração para o **post automático** de cada dia.

Todo post termina com uma seção **"O que isso significa para o seu negócio"** (ações concretas para um distribuidor ou uma loja de autopeças), **perguntas frequentes** e a lista de **fontes**.

## Histórico

Quatro listas, com busca:

- **Posts**: os gerados, filtráveis por status (para revisar, aprovados, publicados, rejeitados).
- **Posts descartados**: os que o sistema escreveu mas não passaram nos controles, com o motivo.
- **Artigos salvos** e **artigos descartados**: as notícias coletadas, com o motivo do descarte.

### Revisar um post

Ao abrir um post você vê o texto e, ao lado, o que o sistema revisou:

- **Dados versus notícias**: quantos dados têm respaldo e quais não. Revise os marcados como "sem respaldo" antes de publicar.
- **Estilo e SEO**: frases de enchimento, anglicismos, tamanho do título e da meta description, palavra-chave, perguntas frequentes.
- **Custo deste post**, se a API paga foi usada.
- **Imagem de destaque** e **o plano** que o post seguiu.

Ações:

| Botão | O que faz |
|---|---|
| **Aprovar e enviar ao HubSpot** / **Rejeitar** | Aprovar envia o post como rascunho ao blog do seu idioma, assinado pelo autor escolhido no bloco **Publicação no HubSpot** (padrão: Gastón Zelerteins). Rejeitar pede um motivo, que os próximos posts levam em conta |
| **Editar** | Altera o texto. A primeira edição guarda a versão original, e os próximos posts aprendem com suas alterações |
| **Pré-visualização** | Como vai ficar no blog: título, meta description, etiquetas, imagem e corpo. Ali também se troca a imagem |
| **Enviar rascunho ao HubSpot** / **Publicar no HubSpot** | Só com o post aprovado. "Enviar rascunho" tenta de novo se o envio falhou ao aprovar |

### Avaliar posts

No post aberto: de 1 a 5 estrelas, etiquetas ("Parece IA", "Muito longo ou repetitivo", "Bom ângulo"…) e um comentário opcional. É a forma mais direta de melhorar os posts:

- Uma etiqueta negativa que se repete adiciona uma regra aos próximos posts.
- Os comentários de posts mal avaliados são usados como correções; os dos bem avaliados, como exemplos do que funciona.
- Os posts com 4 ou 5 estrelas passam a ser referências de estilo.
- Com 8 posts avaliados, a revisão automática se ajusta ao seu critério.

Em **Histórico → Como a geração aprende** você vê tudo o que o sistema aprendeu.

### Imagem de destaque

Cada post novo sai com a foto de uma das notícias que usou. Na **Pré-visualização** você pode escolher a foto de outra das suas notícias, colar a URL de uma imagem própria ou removê-la. Ao publicar, a imagem é copiada ao HubSpot. Atenção: são fotos de outros veículos; confira se podem ser usadas antes de publicar.

## Agendamento

A que horas e a cada quantos dias se **buscam notícias** e se **escreve o post automático**, e quantos artigos são lidos por fonte. As alterações valem ao tocar em **Salvar alterações**. Os horários são da Argentina.

## Fontes

Os sites verificados para buscar notícias.

- **Adicionar** inclui a fonte direto.
- **Testar e adicionar** verifica primeiro e só adiciona se encontrar artigos do setor.
- **Pausar** deixa de verificá-la sem excluí-la.
- **Buscar recomendações** sugere sites novos do setor.

## Execuções

O que o sistema está executando (buscar notícias, gerar um post) e o que aguarda a vez, com o registro de cada etapa. Roda uma coisa por vez: o que você pedir enquanto isso fica na fila. Uma execução pendente pode ser cancelada.

## API paga

A **API paga** é escolhida na visualização Desenvolvedor, em **Provedor de IA**, e se diferencia das demais pelo ícone **$**. Gera posts de mais qualidade, mas cada etapa custa dinheiro: ao escolhê-la, pede confirmação e mostra quanto foi gasto no mês. Fica assim até você escolher outro provedor. Há um limite de gasto mensal: se for atingido, o sistema passa sozinho ao provedor gratuito.

## Visualização Cliente e Desenvolvedor

- **Cliente** mostra o essencial.
- **Desenvolvedor** adiciona o console de processos, as estatísticas técnicas e a escolha do provedor de IA.

## Perguntas frequentes

**Por que um post saiu em português?**
Porque o Brasil estava entre as regiões. Desmarque em Criar post → Mais opções.

**O que faço com um dado "sem respaldo"?**
Procure nas notícias do post (estão ao lado). Se não estiver, edite o post e remova ou altere.

**O post não tem imagem.**
Nenhuma das suas notícias tinha foto. Cole a URL de uma imagem pela Pré-visualização.

**Como faço para os posts melhorarem?**
Avalie, conte no comentário o que você mudaria e, ao rejeitar um, escreva o motivo. O sistema usa isso nos próximos.

**Onde vejo quanto custou um post?**
Ao abri-lo, em "Custo deste post" (só se a API paga foi usada).

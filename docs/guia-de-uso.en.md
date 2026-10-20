# User guide

AfterDrive Intelligence finds auto parts industry news on the sites you choose, filters it with artificial intelligence and uses it to write B2B posts for the AfterDrive by Alephee blog. You review each post, fix it if needed and publish it on HubSpot.

This guide explains every part of the application. For a quick on-screen tour: **Help → Replay the tutorial**, at the bottom of the sidebar.

> The interface language (Español, Português, English) is changed with the **ES / PT / EN** buttons at the top right, or on the first step of the tutorial. It only changes the interface: the language of each post depends on its region (see **Create post**). The technical documentation is in Spanish.

## How it works, in three steps

1. **Collect news.** Every day, at the time you schedule, the system checks your sources, keeps the new industry news and discards the rest (for example, new car sales or insurance). For each news item it saves a card with its key facts.
2. **Write the post.** With the most useful and recent news, the system makes a plan, writes the post, checks that every figure and every company comes from the news, reviews style and SEO and, if it finds a problem, fixes it. It also generates a featured image.
3. **Review and publish.** The post lands in **History** as "To review". You read it, rate it, edit it if you want, approve it and publish it on the blog.

## Home

Today's content:

- **Posts to review**, news ready to use, active sources and when the next automatic post comes out. Tap any of them to jump there.
- **Latest post** generated, with a button to read it.
- **To review**: posts waiting for you to read them.
- **System activity**: what it's doing right now.

## Create post

To write a post whenever you want, without waiting for the automatic one.

| Option | What it's for |
|---|---|
| **Categories** | The post's topic. Choose one or more |
| **Tone** | Commercial, analytical-technical, journalistic, explanatory or executive |
| **Approximate length** | Short (500 to 700 words), medium (700 to 1000) or long (1000 to 1400) |
| **Specific topic** | Optional, to narrow it down ("dropshipping in Argentina") |
| **Link target** | A link the post should lead the reader to |
| **Regions** (under "More options") | The market and the language. With Brazil the post is written in Portuguese; with no region, in Rioplatense Spanish |
| **Clients** (under "More options") | Companies the post can mention as real cases |

- **Generate post** writes it with what's on screen. It takes a few minutes; you can keep using the application meanwhile.
- **Save changes** keeps these settings for the daily **automatic post**.

Every post ends with a **"What it means for your business"** section (concrete actions for a distributor or a parts store), **frequently asked questions** and the list of **sources**.

## History

Four lists, with a search box:

- **Posts**: the generated ones, filterable by status (to review, approved, published, rejected).
- **Discarded posts**: the ones the system wrote but that didn't pass its checks, with the reason.
- **Saved articles** and **discarded articles**: the news that was scraped, with the reason it was discarded.

### Reviewing a post

When you open a post you see the text and, on the side, what the system checked:

- **Facts vs. the news**: how many facts are backed up and which aren't. Check the ones marked "unsupported" before publishing.
- **Style and SEO**: filler phrases, anglicisms, title and meta description length, keyword, FAQ.
- **Cost of this post**, if the paid API was used.
- **Featured image** and **the plan** the post followed.

Actions:

| Button | What it does |
|---|---|
| **Approve** / **Reject** | Rejecting asks for a reason, which upcoming posts take into account |
| **Edit** | Changes the text. The first edit keeps the original version, and upcoming posts learn from your changes |
| **Preview** | How it will look on the blog: title, meta description, tags, image and body. The image can also be changed there |
| **Draft on HubSpot** / **Publish on HubSpot** | Only for approved posts |

### Rating posts

On the open post: 1 to 5 stars, tags ("Sounds like AI", "Too long or repetitive", "Good angle"…) and an optional comment. It's the most direct way to improve the posts:

- A negative tag that keeps coming up adds a rule for upcoming posts.
- Comments on low-rated posts are used as corrections; those on well-rated posts, as examples of what works.
- Posts with 4 or 5 stars become style references.
- With 8 rated posts, the automatic review adjusts to your judgment.

In **History → How generation learns** you see everything the system learned.

### Featured image

Every new post comes with an AI-generated image (NVIDIA, free). In **Preview** you can generate another one, describe what you want it to show (ideally in English), paste the URL of your own image or remove it. When publishing, the image is uploaded to HubSpot.

## Schedule

When and how often **news is fetched** and **the automatic post is written**, and how many articles are read per source. Changes apply when you tap **Save changes**. Times are Argentina time.

## Sources

The sites checked for news.

- **Add** adds the source directly.
- **Test and add** checks it first and only adds it if it finds industry articles.
- **Pause** stops checking it without deleting it.
- **Find recommendations** suggests new industry sites.

## Runs

What the system is running (fetching news, generating a post) and what's waiting its turn, with a log of every step. It runs one thing at a time: anything you request meanwhile is queued. A pending run can be canceled.

## Paid API

The **Paid API** is chosen in the Developer view, under **AI provider**, and stands out from the others with the **$** icon. It gives higher-quality posts, but every step costs money: choosing it asks for confirmation and shows how much was spent this month. It stays on until you pick another provider. There's a monthly spending cap: if it's reached, the system switches to the free provider on its own.

## Client and Developer view

- **Client** shows the essentials.
- **Developer** adds the process console, technical statistics and the choice of AI provider.

## FAQ

**Why did a post come out in Portuguese?**
Because Brazil was among the regions. Uncheck it in Create post → More options.

**What do I do with an "unsupported" fact?**
Look for it in the post's news (they're on the side). If it isn't there, edit the post and remove or change it.

**The post has no image.**
When you open it, the "Featured image" block says why. Generate one from Preview.

**How do I make the posts better?**
Rate them, say in the comment what you'd change and, when you reject one, write the reason. The system uses it in the next ones.

**Where do I see how much a post cost?**
When you open it, under "Cost of this post" (only if the paid API was used).

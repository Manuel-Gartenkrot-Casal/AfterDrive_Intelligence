# User guide

AfterDrive Intelligence finds auto parts industry news on the sites you choose, filters it with artificial intelligence and uses it to write B2B posts for the AfterDrive by Alephee blog. You review each post, fix it if needed and upload it to HubSpot as a draft; the final publishing is done in HubSpot.

This guide explains every part of the application. For an on-screen tour: **Help**, at the bottom of the sidebar. It has the full tutorial and three short ones: **Create my first article**, **Review and publish** and **Schedule tasks**.

> The interface language (Español, Português, English) is changed with the **ES / PT / EN** buttons at the top right, or on the first step of the tutorial. It only changes the interface, not the posts: every post is written in Portuguese and translated into Spanish and English (see **Create post**). The technical documentation is in Spanish.

## How it works, in three steps

1. **Collect news.** Every day, at the time you schedule, the system checks your sources, keeps the new industry news and discards the rest (for example, new car sales or insurance). For each news item it saves a card with its key facts.
2. **Write the post.** With the most useful and recent news, the system makes a plan, writes the post, checks that every figure and every company comes from the news, reviews style and SEO and, if it finds a problem, fixes it. It picks 3 photos from those stories, translates the post into the other two languages and an AI rates it.
3. **Review and upload.** The post lands in **History** as "To review". You review it, rate it, edit it if you want and approve it: it's uploaded to HubSpot as a draft, in Portuguese, Spanish and English.

The screen updates itself every few seconds: whatever another person or a system task changes shows up without reloading. If someone changed the post you have open, a notice with **Refresh** appears.

## Home

Today's content:

- **Posts to review**, news ready to use, active sources and when the next automatic post comes out. Tap any of them to jump there.
- **Latest post** generated, with a button to read it.
- **To review**: posts waiting for you to read them.
- **System activity**: what it's doing right now.

In the Developer view, Home shows a dashboard instead, with what scraping brought in, the posts written, the runs and AI usage.

## Create post

To write a post whenever you want, without waiting for the automatic one.

| Option | What it's for |
|---|---|
| **Categories** | The post's topic. Choose one or more |
| **Tone** | Commercial, analytical-technical, journalistic, explanatory or executive |
| **Approximate length** | Short (500 to 700 words), medium (700 to 1000) or long (1000 to 1400) |
| **Specific topic** | Optional, to narrow it down ("dropshipping in Argentina") |
| **Link target** | A link the post should lead the reader to |
| **Regions** (under "More options") | The market the post talks about. **They don't change the language** |
| **Clients** (under "More options") | Companies the post can mention as real cases |

**Article language** shows which language it's written in: Portuguese. As soon as it's created, it's translated into Spanish and English; all three versions can be read and edited in History.

- **Generate post** writes it with what's on screen. It takes a few minutes; you can keep using the application meanwhile. While it's being written you see which step it's on and you can cancel it (nothing is saved).
- **Save changes** keeps these settings for the daily **automatic post**.

Every post ends with a **"What it means for your business"** section (concrete actions for a distributor or a parts store), **frequently asked questions** and the list of **sources**.

## History

Four lists, with a search box:

- **Posts**: the generated ones, filterable by status (to review, approved, published, rejected). Each one shows its stars: yours and, marked **AI**, those from the AI rating.
- **Discarded posts**: the ones the system wrote but that didn't pass its checks, with the reason.
- **Saved articles** and **discarded articles**: the news that was scraped, with the reason it was discarded.

### Reviewing a post

When you open a post you see the text and, on the side, the review in three steps. It opens on the first step with something pending. On a phone you choose whether to see the post or the review.

**1. Review**: what the system checked when writing it. First what needs attention, then what's fine; each row has a headline, **Show details** and, when it applies, its action.

- **Facts vs. the news**: how many facts are backed up and which aren't. Check the ones marked "unsupported" before publishing.
- **Similar to a recent post**: whether it's too close to another recent one.
- **Style and SEO**: filler phrases, anglicisms, title and meta description length, keyword, FAQ.
- **Guidelines**, **image** and **languages**.
- **How it was generated**: the plan, the categories, the news, the AfterDrive citations, what it cost (if the paid API was used) and the automatic criteria.

**2. Rate**: the AI rating and yours (see **Rating posts**).

**3. Publish**: the featured image, which HubSpot blog it goes to, with which tag and which author (default: Gastón Zelerteins), and one row per language with **View translation** and **Open in HubSpot**.

The main button, at the bottom right, changes with the step: **Next: rate →** and **Next: publish →** on the first two and, on Publish, the action that applies:

| Button | What it does |
|---|---|
| **Approve and upload to HubSpot** | Approves the post and uploads it as a draft to the blog in its language, signed by the chosen author. Then the translations are uploaded |
| **Upload draft to HubSpot** / **Update draft on HubSpot** | For an approved post: retries if the upload failed, or updates the same draft with your changes |
| **Edit** | Changes the text. The first edit keeps the original version, and upcoming posts learn from your changes |
| **Preview** | How it will look on the blog: title, meta description, tags, image and body. The image can also be changed there |
| **More ▾** | Copy text, View on HubSpot, Back to review and **Reject**, which asks for a reason that upcoming posts take into account |

> **Publishing from the application is turned off for now.** Posts are only uploaded as drafts and published from HubSpot.

### Rating posts

The **Rate** step has two parts:

- **AI rating**: an AI copy editor gives the writing a score from 1 to 10, with bars for grammar, wording, tone and structure, and points out the mistakes it made while writing: the passage, what's wrong and how it should read. It runs on its own when the post is generated (and again when you open it, if you edited it). It's informational: it doesn't count toward learning. It's shown in the interface language; the passage and its fix stay in the post's language.
- **Rate this article**: your rating, 1 to 5 stars, with tags ("Sounds like AI", "Too long or repetitive", "Good angle"…) and an optional comment. If you haven't rated it yet, the rating suggested by the AI judge comes pre-filled; it only counts once you save it.

Your rating is the most direct way to improve the posts:

- A negative tag that keeps coming up adds a rule for upcoming posts.
- Comments on low-rated posts are used as corrections; those on well-rated posts, as examples of what works.
- Posts with 4 or 5 stars become style references.
- With 8 rated posts, the automatic review adjusts to your judgment.

In **History → How generation learns** you see everything the system learned and how often the AI judge matched your rating.

### Images

Every post comes with **3 photos** from the news it used: the featured one (cover) and 2 inside the text. The AI picks them based on the post's topic (with the paid API, it looks at them) and skips logos, banners, charts and photos of something else. Also:

- **The cover never shows people.** A photo with people can go inside the text, but not as the cover. If every suitable photo has people, the post has no cover and the review explains why.
- **Photos aren't repeated**: a photo already used in another post from the last 30 days isn't used again.
- If the post's own news isn't enough, photos are looked for in other news on the same topic.

In **Preview** you can pick the photo of another of its stories (those with people are marked), paste the URL of an image, **drag an image or choose one from your computer** (JPG, PNG, WebP or GIF, up to 5 MB) or remove it. When the post is uploaded, the images are copied to HubSpot. Note: these are photos from other outlets; check they can be used before publishing.

### Other languages and citations

As soon as it's created, the post is translated into Spanish and English. On the open post, the **Português**, **Español** and **English** tabs show each version, which is edited separately. If you edit the main text, the translations become outdated: **Translate again** redoes them.

When you approve and upload the post, each version goes to HubSpot as a draft, linked to the original. You see it in **Activity** and in the **Publish** step. If one fails, **Upload the translations again** retries.

When it fits the topic, the post cites earlier AfterDrive by Alephee posts and links to them. You see them in **How it was generated**.

## Schedule

When and how often **news is fetched** and **the automatic post is written**, and how many articles are read per source. Changes apply when you tap **Save changes**. Times are Argentina time.

## Sources

The sites that are checked for news.

- **Add** adds the source directly.
- **Test and add** checks it first and only adds it if it finds industry articles. If the site doesn't respond, it tells you.
- **Pause** stops checking it without deleting it.
- **Find recommendations** suggests new industry sites: it searches Google News and other search engines and also asks the AI for ideas (each site is verified before being suggested).

## Prompts

The instructions the AI gets when writing each post, in pieces (identity, audience, data rules, Alephee focus, format, SEO and one per persona). Every manual change goes through draft, review and approval.

Prompts has two tabs: **Current prompts** (the ones above) and **AI prompts**, which improves them without you writing them. The AI reads how posts are rated (the critique, the judge, your ratings and the Alephee checklist), finds what keeps happening and which piece to change, and edits a **copy** of the prompts. The current prompts never change from here.

- **Automatic improvement**: when on, the AI improves the copy on its own every 5 new posts.
- **Analyze and improve now** does it right away.
- The tab shows the full AI prompt with what changed marked in green (what was removed, in red), the post analysis, the history and a box to ask for a change manually (for example, "use voseo throughout the post").
- If you don't like a change, **Undo the last one**; **Back to current** deletes the changes to a piece.
- **Use these prompts** makes writing use the AI ones; the tab in use says **In use**.

## Activity

What the system is running (fetching news, generating a post, uploading translations) and what's waiting its turn, with a log of every step. It runs one thing at a time: anything you request meanwhile is queued. Any task can be cancelled, including the one that's running. When a scraping run ends, the log says how much of the paid API it spent.

While something runs, a floating panel at the bottom right shows it from any section; you can collapse it.

In the Developer view, while something runs, the **terminal** shows up at the bottom with the live log and, in the **Queue** tab, what's waiting. Drag its top edge to make it taller, maximize or hide it with the buttons on the right, and close it with the ×.

## Paid API

The **paid API** is chosen in the Developer view, under **AI provider**, and stands out from the rest with the **$** icon. It produces higher-quality posts, but every step costs money: when you pick it, it asks for confirmation and shows how much was spent this month. It stays that way until you choose another provider. There's a monthly spending cap: if it's reached, the system switches to the free provider on its own.

## Client and Developer view

- **Client** shows the essentials. To switch to Developer or log out, tap your user at the bottom of the sidebar.
- **Developer** adds the process console, the metrics dashboard, the AI provider choice and two switches:
  - **HubSpot drafts → blog_test**: on, drafts go to the HubSpot test blog instead of the blog for each language. If the server has no test blog configured, it shows as disabled.
  - **Auto-approval**: on, a post from the scheduled generation that passes the checks and the AI judge (with good confidence) is approved on its own and uploaded to HubSpot as a draft. If it doesn't pass, it waits for review with the reasons. It never publishes. Posts you generate by hand always wait for your review.

## FAQ

**Why are posts written in Portuguese?**
Because it's the blog's main language. Each post is translated into Spanish and English when it's created: switch tabs on the open post.

**What do I do with an "unsupported" fact?**
Look for it in the post's news (under **How it was generated**). If it isn't there, edit the post and remove or change it.

**The post has no featured image.**
None of its news photos was suitable, or they all showed people; the reason is in the Review step. Pick another one from Preview, paste a URL or upload an image from your computer.

**Why can't I publish from here?**
It's turned off for now: the post is uploaded as a draft and published from HubSpot.

**How do I make the posts better?**
Rate them, say in the comment what you'd change and, when you reject one, write the reason. The system uses it in the next ones.

**Where do I see how much a post cost?**
When you open it, under **How it was generated** (only if the paid API was used).

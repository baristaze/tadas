# Slack

The one Slack channel an org connects, the codes that connect it, and the
record of what Tadas posted there. This is one of the kinds of thing
[Tadas is made of](../../../../README.md).

## The nouns

- **Connection**: the Slack workspace and channel an org is connected
  to, who linked it, and whether posting there works. An org has at
  most one, and a channel belongs to at most one org.
- **Link code**: a short code, like `ABCD-EFGH`, that an owner or an
  admin asks for in Tadas and types into the channel as
  `/tadas link ABCD-EFGH`. Tadas keeps only its fingerprint, never the
  code. It works once and stops working after ten minutes.
- **Post**: one message Tadas put in the channel, named by the job that
  posted it, so the same job never posts twice.

## What can happen

- **Ask for a code.** An owner or an admin asks; the code is shown once.
- **Link a channel.** `/tadas link <code>` in the channel spends the
  code and makes the channel the org's connection. Linking again, with
  a new code, replaces the channel.
- **Disconnect.** An owner or an admin ends the connection.
- **Post.** A reminder going out, a task created, and a task completed
  are each posted in the connected channel.
- **Break.** When Slack refuses a post for good (the channel is gone,
  archived, or Tadas was never invited into it), the connection says
  so and posting stops until someone links a channel again.
- **Add a task from Slack.** `/tadas add <title>` in a connected
  channel creates a task in the org, and does nothing else.
- **Sweep.** Ended connections, spent codes, and the record of posts
  are erased after the retention, thirty days by default.

## The rules

- **A channel speaks for one org.** A channel another org holds cannot
  be linked; that org disconnects it first.
- **A code works once.** Spending it is one conditional write, so two
  people typing the same code link one channel.
- **A task added from Slack is the linker's.** It is created on the
  org's behalf and attributed to the member whose code linked the
  channel. To change who that is, link the channel again.
- **Only an owner or an admin connects or disconnects.** Every member
  sees the connection.
- **Nothing a person typed is sent to Slack unescaped.** A title that
  reads `<!channel>` does not ping anyone.

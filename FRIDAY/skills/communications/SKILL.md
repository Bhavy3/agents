# Communications Skill

## Purpose
Guidelines for handling email notifications, drafting messages, and external communication workflows.

## Grounding & Safety Constraints
1. **Never Fabricate Data**: Only inspect or summarize emails detected by the real `MailWatcherWorker` or explicit user queries.
2. **Read-Only Inspection**: Do not send external emails or broadcast messages without explicit confirmation.
3. **Sensitive Content Filtering**: Redact authentication tokens, passwords, and sensitive keys from summaries.
4. **Tool Use**: Use `n8n_create_workflow` or official connectors when automating message webhooks.

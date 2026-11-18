# Browser skill

Use Playwright for websites when available. Use `browser_open`,
`browser_snapshot`, `browser_click`, and `browser_type`.

After every navigation or action, take a fresh snapshot and verify the result.
Use Agent Desktop only for native application surfaces or when a site cannot be
operated reliably through the DOM.

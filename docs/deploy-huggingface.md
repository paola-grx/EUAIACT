# Free demo on Hugging Face Spaces (no payment card)

This runs the app as a **demo**: fictional sample data, and a database that resets whenever
the Space restarts or wakes up from sleep. It's for looking around, not for real use.

## Steps

1. Create a free account at huggingface.co.
2. **New > Space**:
   - **Space name:** e.g. `euaiact-demo`
   - **SDK:** Docker (template: Blank)
   - **Hardware:** CPU basic (free)
   - **Visibility:** Public or Private. A private Space is only reachable while you are
     signed in to Hugging Face.
3. In the new Space, open **Files > Add file > Upload files** and upload the two files from
   [`deploy/huggingface/`](../deploy/huggingface) in this repository: `Dockerfile` and
   `README.md`. Replace the Space's existing README.md.
4. Commit. The Space builds (a few minutes; progress is under **Logs**).
5. Open the app **directly** at `https://<your-user>-euaiact-demo.hf.space`. The preview on
   the Space page stays blank, because the app refuses to be embedded in other pages.
6. Create the admin account straight away (until you do, anyone who opens the address can
   create it), complete the onboarding, and explore the sample data.

## Good to know

- **Sleep:** free Spaces sleep after a period without visitors (currently about 48 hours).
  The next visit wakes the Space, and the demo starts again with fresh sample data.
- **Updates:** the Space pulls the app from the `main` branch on GitHub when it builds. To
  pick up later changes, use **Settings > Factory rebuild** in the Space.
- **Sessions:** without a configured secret, each restart logs everyone out. To avoid that,
  add a Space secret `EUAIACT_SECRET_KEY` (a random value of at least 32 characters) under
  **Settings > Variables and secrets**.
- **Never enter real personal data.** For real use, deploy with PostgreSQL (see
  [deploy-render.md](deploy-render.md) or the Docker Compose setup in the README).

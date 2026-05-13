export interface Env {
  GITHUB_TOKEN: string;
  GITHUB_REPO: string;
  GITHUB_LABELS?: string;
  GITHUB_ASSIGNEES?: string;
  BREVO_API_KEY?: string;
  RESEND_API_KEY?: string;
  POSTMARK_SERVER_TOKEN?: string;
  SUPPORT_EMAIL?: string;
  FROM_EMAIL?: string;
  FEEDBACK_SHARED_SECRET?: string;
}

type RecentError = {
  timestamp?: number;
  site?: string;
  exc_class?: string;
  message?: string;
  tool?: string | null;
};

type FeedbackPayload = {
  session_id?: string;
  type?: string;
  content?: string;
  version?: string;
  os?: string;
  model?: string;
  recent_errors?: RecentError[];
};

const MAX_CONTENT_LENGTH = 10_000;
const MAX_RECENT_ERRORS = 10;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return corsResponse(null, 204);
    }
    if (request.method !== "POST") {
      return jsonResponse({ error: "method_not_allowed" }, 405);
    }

    if (env.FEEDBACK_SHARED_SECRET) {
      const auth = request.headers.get("authorization") || "";
      if (auth !== `Bearer ${env.FEEDBACK_SHARED_SECRET}`) {
        return jsonResponse({ error: "unauthorized" }, 401);
      }
    }

    let payload: FeedbackPayload;
    try {
      payload = await request.json<FeedbackPayload>();
    } catch {
      return jsonResponse({ error: "invalid_json" }, 400);
    }

    const content = (payload.content || "").trim();
    const recentErrors = Array.isArray(payload.recent_errors)
      ? payload.recent_errors.slice(0, MAX_RECENT_ERRORS)
      : [];
    if (!content && recentErrors.length === 0) {
      return jsonResponse({ error: "empty_feedback" }, 400);
    }
    if (content.length > MAX_CONTENT_LENGTH) {
      return jsonResponse({ error: "feedback_too_large" }, 413);
    }

    const sanitizedPayload: FeedbackPayload = {
      session_id: trim(payload.session_id, 128),
      type: trim(payload.type || "feedback", 32),
      content,
      version: trim(payload.version, 64),
      os: trim(payload.os, 128),
      model: trim(payload.model, 128),
      recent_errors: recentErrors.map(sanitizeRecentError),
    };

    const title = githubTitle(sanitizedPayload);
    const body = githubBody(sanitizedPayload, request);

    await createGithubIssue(env, title, body);
    await sendSupportEmail(env, title, body);

    return corsResponse(null, 204);
  },
};

function trim(value: unknown, maxLength: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return trimmed.slice(0, maxLength);
}

function sanitizeRecentError(error: RecentError): RecentError {
  return {
    timestamp: typeof error.timestamp === "number" ? error.timestamp : undefined,
    site: trim(error.site, 128),
    exc_class: trim(error.exc_class, 128),
    message: trim(error.message, 500),
    tool: trim(error.tool, 128) || null,
  };
}

function githubTitle(payload: FeedbackPayload): string {
  const prefix = payload.type === "error" ? "Error report" : "Feedback";
  const version = payload.version ? ` ${payload.version}` : "";
  const suffix = payload.session_id ? ` (${payload.session_id.slice(0, 8)})` : "";
  return `[Pythinker CLI] ${prefix}${version}${suffix}`;
}

function githubBody(payload: FeedbackPayload, request: Request): string {
  const lines = [
    "## User submission",
    "",
    payload.content || "_(no comment)_",
    "",
    "## Context",
    "",
    `- Type: ${payload.type || "feedback"}`,
    `- Session: ${payload.session_id || "unknown"}`,
    `- Version: ${payload.version || "unknown"}`,
    `- OS: ${payload.os || "unknown"}`,
    `- Model: ${payload.model || "unknown"}`,
    `- Received at: ${new Date().toISOString()}`,
    `- CF ray: ${request.headers.get("cf-ray") || "unknown"}`,
  ];

  if (payload.recent_errors?.length) {
    lines.push("", "## Recent errors", "");
    for (const error of payload.recent_errors) {
      lines.push(
        `- ${error.site || "unknown"}: ${error.exc_class || "unknown"}` +
          `${error.tool ? ` (tool=${error.tool})` : ""}` +
          `${error.message ? ` — ${error.message}` : ""}`,
      );
    }
  }

  return lines.join("\n");
}

async function createGithubIssue(env: Env, title: string, body: string): Promise<void> {
  const labels = splitCsv(env.GITHUB_LABELS || "feedback,pythinker-cli");
  const assignees = splitCsv(env.GITHUB_ASSIGNEES || "");
  const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "pythinker-feedback-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ title, body, labels, assignees }),
  });

  if (!response.ok) {
    throw new Error(`GitHub issue creation failed: ${response.status}`);
  }
}

async function sendSupportEmail(env: Env, subject: string, body: string): Promise<void> {
  const to = env.SUPPORT_EMAIL || "support@pythinker.com";
  const from = env.FROM_EMAIL || "Pythinker Feedback <feedback@pythinker.com>";

  if (env.BREVO_API_KEY) {
    const sender = parseMailbox(from);
    const response = await fetch("https://api.brevo.com/v3/smtp/email", {
      method: "POST",
      headers: {
        "api-key": env.BREVO_API_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        sender,
        to: [{ email: to }],
        subject,
        textContent: body,
      }),
    });
    if (!response.ok) {
      throw new Error(`Brevo email failed: ${response.status}`);
    }
    return;
  }

  if (env.RESEND_API_KEY) {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ from, to, subject, text: body }),
    });
    if (!response.ok) {
      throw new Error(`Resend email failed: ${response.status}`);
    }
    return;
  }

  if (env.POSTMARK_SERVER_TOKEN) {
    const response = await fetch("https://api.postmarkapp.com/email", {
      method: "POST",
      headers: {
        "X-Postmark-Server-Token": env.POSTMARK_SERVER_TOKEN,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ From: from, To: to, Subject: subject, TextBody: body }),
    });
    if (!response.ok) {
      throw new Error(`Postmark email failed: ${response.status}`);
    }
  }
}

function parseMailbox(value: string): { email: string; name?: string } {
  const match = value.match(/^(.+?)\s*<([^>]+)>$/);
  if (!match) return { email: value.trim() };
  return { name: match[1].trim().replace(/^"|"$/g, ""), email: match[2].trim() };
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function corsResponse(body: BodyInit | null, status: number): Response {
  return new Response(body, { status, headers: corsHeaders() });
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(), "Content-Type": "application/json" },
  });
}

function corsHeaders(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
}

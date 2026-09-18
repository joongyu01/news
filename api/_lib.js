// 검토 페이지 API가 공유하는 부분: 로그인 세션과 GitHub 저장소 읽기/쓰기.
//
// 별도 데이터베이스를 두지 않고 GitHub 저장소에 직접 커밋합니다.
// 제외 이력이 커밋 로그로 남아서, 나중에 "그날 왜 이 기사가 빠졌지"를
// 되짚을 수 있습니다.

import crypto from "node:crypto";

const SESSION_COOKIE = "kpetro_session";
const SESSION_HOURS = 12;

// --- 설정 ------------------------------------------------------------------

export function settings() {
  const repo = process.env.GH_REPO || "";
  return {
    pin: process.env.REVIEW_PIN || "",
    secret: process.env.SESSION_SECRET || "",
    token: process.env.GH_TOKEN || "",
    repo,
    branch: process.env.GH_BRANCH || "main",
    supabaseUrl: (process.env.SUPABASE_URL || "").trim().replace(/\/$/, ""),
    supabaseKey: (process.env.SUPABASE_SERVICE_ROLE_KEY || "").trim(),
  };
}

export function missingSettings() {
  const s = settings();
  const storageKeys = s.supabaseUrl || s.supabaseKey
    ? ["supabaseUrl", "supabaseKey"] : ["token", "repo"];
  return ["pin", "secret", ...storageKeys].filter((k) => !s[k]);
}

// --- 세션 ------------------------------------------------------------------

function sign(payload, secret) {
  return crypto.createHmac("sha256", secret).update(payload).digest("base64url");
}

/** 타이밍 공격을 막기 위해 길이가 달라도 상수 시간에 비교합니다. */
function safeEqual(a, b) {
  const ha = crypto.createHash("sha256").update(String(a)).digest();
  const hb = crypto.createHash("sha256").update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

export function issueSession(secret) {
  const expires = Date.now() + SESSION_HOURS * 3600 * 1000;
  const payload = String(expires);
  return `${payload}.${sign(payload, secret)}`;
}

export function verifySession(req) {
  const { secret } = settings();
  if (!secret) return false;

  const raw = (req.headers.cookie || "")
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${SESSION_COOKIE}=`));
  if (!raw) return false;

  const value = decodeURIComponent(raw.slice(SESSION_COOKIE.length + 1));
  const [payload, mac] = value.split(".");
  if (!payload || !mac) return false;
  if (!safeEqual(mac, sign(payload, secret))) return false;
  return Number(payload) > Date.now();
}

export function setSessionCookie(res, value, maxAgeSeconds) {
  res.setHeader(
    "Set-Cookie",
    [
      `${SESSION_COOKIE}=${encodeURIComponent(value)}`,
      "Path=/",
      "HttpOnly",
      "Secure",
      "SameSite=Strict",
      `Max-Age=${maxAgeSeconds}`,
    ].join("; ")
  );
}

export function checkPin(input) {
  const { pin } = settings();
  return Boolean(pin) && safeEqual(String(input || ""), pin);
}

// --- GitHub 저장소 ---------------------------------------------------------

const API = "https://api.github.com";

function supabaseTarget(path) {
  const s = settings();
  if (!s.supabaseUrl && !s.supabaseKey) return null;
  if (!s.supabaseUrl || !s.supabaseKey) throw new Error("Supabase 설정이 불완전합니다");
  const match = /^data\/(drafts|exclusions)\/(\d{4}-\d{2}-\d{2})\.json$/.exec(path);
  if (!match) throw new Error("지원하지 않는 뉴스 경로입니다");
  return {
    url: `${s.supabaseUrl}/rest/v1/news_${match[1]}`,
    date: match[2],
    headers: { apikey: s.supabaseKey, Authorization: `Bearer ${s.supabaseKey}` },
  };
}

function ghHeaders() {
  const { token } = settings();
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "kpetro-news-review",
  };
}

/** 파일을 읽어 {json, sha} 로 돌려줍니다. 없으면 null. */
export async function readFile(path) {
  const target = supabaseTarget(path);
  if (target) {
    const response = await fetch(`${target.url}?date=eq.${target.date}&select=payload`, {
      headers: target.headers, signal: AbortSignal.timeout(25000),
    });
    if (!response.ok) throw new Error(`Supabase 읽기 실패 ${response.status}`);
    const rows = await response.json();
    return rows.length ? { json: rows[0].payload } : null;
  }
  const { repo, branch } = settings();
  const url = `${API}/repos/${repo}/contents/${path}?ref=${encodeURIComponent(branch)}`;
  const resp = await fetch(url, { headers: ghHeaders() });

  if (resp.status === 404) return null;
  if (!resp.ok) {
    throw new Error(`GitHub 읽기 실패 ${resp.status}: ${await resp.text()}`);
  }
  const body = await resp.json();
  const text = Buffer.from(body.content, "base64").toString("utf-8");
  return { json: JSON.parse(text), sha: body.sha };
}

/** 파일을 쓰고 커밋합니다. sha 를 주면 덮어쓰기, 없으면 새로 만듭니다. */
export async function writeFile(path, data, message, sha) {
  const target = supabaseTarget(path);
  if (target) {
    const response = await fetch(`${target.url}?on_conflict=date`, {
      method: "POST", signal: AbortSignal.timeout(25000),
      headers: { ...target.headers, "Content-Type": "application/json",
        Prefer: "resolution=merge-duplicates,return=minimal" },
      body: JSON.stringify({ date: target.date, payload: data, updated_at: new Date().toISOString() }),
    });
    if (!response.ok) throw new Error(`Supabase 쓰기 실패 ${response.status}`);
    return { ok: true };
  }
  const { repo, branch } = settings();
  const resp = await fetch(`${API}/repos/${repo}/contents/${path}`, {
    method: "PUT",
    headers: { ...ghHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      content: Buffer.from(JSON.stringify(data, null, 2) + "\n", "utf-8").toString("base64"),
      branch,
      ...(sha ? { sha } : {}),
    }),
  });
  if (!resp.ok) {
    throw new Error(`GitHub 쓰기 실패 ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

// --- 공통 ------------------------------------------------------------------

/** 오늘 날짜 (KST). 서버 시간대와 무관하게 동작해야 합니다. */
export function todayKST() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function isValidDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || "");
}

export function json(res, status, body) {
  res.status(status).setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

export function requireAuth(req, res) {
  if (verifySession(req)) return true;
  json(res, 401, { error: "인증이 필요합니다" });
  return false;
}

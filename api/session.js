// 로그인 / 로그아웃. PIN 하나로만 지킵니다.
import {
  checkPin, issueSession, missingSettings, setSessionCookie, settings, json,
} from "./_lib.js";

// 4자리 PIN은 무차별 대입이 가능한 길이입니다. 서버리스라 시도 횟수를
// 저장해둘 곳이 없으므로, 대신 실패할 때마다 1초씩 지연시켜 자동화 공격의
// 속도를 떨어뜨립니다. URL 자체를 공개하지 않는 것이 더 중요한 방어선입니다.
const FAIL_DELAY_MS = 1000;

export default async function handler(req, res) {
  if (req.method === "DELETE") {
    setSessionCookie(res, "", 0);
    return json(res, 200, { ok: true });
  }
  if (req.method !== "POST") {
    return json(res, 405, { error: "허용되지 않은 메서드입니다" });
  }

  const missing = missingSettings();
  if (missing.length) {
    return json(res, 500, {
      error: `Vercel 환경변수가 설정되지 않았습니다: ${missing.join(", ")}`,
    });
  }

  const pin = (req.body && req.body.pin) || "";
  if (!checkPin(pin)) {
    await new Promise((r) => setTimeout(r, FAIL_DELAY_MS));
    return json(res, 401, { error: "PIN이 올바르지 않습니다" });
  }

  setSessionCookie(res, issueSession(settings().secret), 12 * 3600);
  return json(res, 200, { ok: true });
}

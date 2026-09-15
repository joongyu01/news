// 제외 목록 저장. 클릭할 때마다 GitHub 저장소에 커밋됩니다.
import {
  isValidDate, json, readFile, requireAuth, writeFile,
} from "./_lib.js";

export default async function handler(req, res) {
  if (req.method !== "PUT" && req.method !== "POST") {
    return json(res, 405, { error: "허용되지 않은 메서드입니다" });
  }
  if (!requireAuth(req, res)) return;

  const { date, excluded, note } = req.body || {};
  if (!isValidDate(date)) {
    return json(res, 400, { error: "날짜 형식이 올바르지 않습니다" });
  }
  if (!Array.isArray(excluded) || excluded.some((id) => typeof id !== "string")) {
    return json(res, 400, { error: "excluded 는 문자열 배열이어야 합니다" });
  }

  // 실제 초안에 있는 기사 id 만 남깁니다. 오래된 화면이 이미 사라진 id를
  // 계속 들고 있어도 파일이 지저분해지지 않습니다.
  let valid;
  try {
    const draft = await readFile(`data/drafts/${date}.json`);
    if (!draft) return json(res, 404, { error: `${date} 초안이 없습니다` });
    valid = new Set((draft.json.articles || []).map((a) => a.id));
  } catch (err) {
    return json(res, 502, { error: String(err.message || err) });
  }

  const clean = [...new Set(excluded)].filter((id) => valid.has(id));
  const path = `data/exclusions/${date}.json`;

  try {
    const existing = await readFile(path);
    const payload = {
      date,
      excluded: clean,
      note: typeof note === "string" ? note.slice(0, 500) : "",
      updated_at: new Date().toISOString(),
    };
    await writeFile(
      path,
      payload,
      `검토: ${date} 기사 ${clean.length}건 제외`,
      existing ? existing.sha : undefined
    );
    return json(res, 200, { ok: true, excluded: clean, count: clean.length });
  } catch (err) {
    return json(res, 502, { error: String(err.message || err) });
  }
}

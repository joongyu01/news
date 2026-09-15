// 그날의 초안과 현재 제외 목록을 함께 내려줍니다.
import {
  isValidDate, json, readFile, requireAuth, todayKST,
} from "./_lib.js";

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return json(res, 405, { error: "허용되지 않은 메서드입니다" });
  }
  if (!requireAuth(req, res)) return;

  const date = isValidDate(req.query.date) ? req.query.date : todayKST();

  let draft, exclusions;
  try {
    // 초안과 제외 목록은 서로 독립이라 동시에 읽습니다.
    [draft, exclusions] = await Promise.all([
      readFile(`data/drafts/${date}.json`),
      readFile(`data/exclusions/${date}.json`),
    ]);
  } catch (err) {
    return json(res, 502, { error: String(err.message || err) });
  }

  if (!draft) {
    return json(res, 404, {
      error: `${date} 초안이 아직 없습니다`,
      date,
      hint: "수집 작업은 매일 06:40에 돕니다.",
    });
  }

  const excluded = exclusions ? exclusions.json.excluded || [] : [];
  const d = draft.json;

  // 섹터 정의가 없는 옛 초안도 열리도록 기사에서 역으로 만들어 줍니다.
  const sectors =
    d.sectors && d.sectors.length
      ? d.sectors
      : [...new Set((d.articles || []).map((a) => a.sector))].map((id) => ({
          id, title: id, limit: 99,
        }));

  return json(res, 200, {
    date: d.date,
    generated_at: d.generated_at || "",
    market: d.market || [],
    sectors: sectors.map((s) => ({
      ...s,
      articles: (d.articles || []).filter((a) => a.sector === s.id),
    })),
    excluded,
    updated_at: exclusions ? exclusions.json.updated_at || "" : "",
  });
}

// 검토 페이지의 미리보기가 실제 발송본과 같은지 대조하기 위한 도구.
//
// public/index.html 안의 스크립트를 그대로 실행한 뒤 plainText() 만 호출합니다.
// 페이지 코드를 복사해오지 않고 원본을 쓰므로, 페이지를 고치면 이 검사도
// 자동으로 새 코드를 검사하게 됩니다.
import fs from "node:fs";
import vm from "node:vm";

const html = fs.readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const source = html.split("<script>")[1].split("</scr" + "ipt>")[0];

// 페이지는 브라우저 전역에 기대어 있습니다. 렌더링에 필요한 최소한만 흉내 냅니다.
const stubElement = () => ({
  hidden: false, textContent: "", innerHTML: "", value: "", disabled: false,
  classList: { add() {}, remove() {} },
  querySelectorAll: () => [], querySelector: () => stubElement(),
  focus() {}, onclick: null, onkeydown: null, onchange: null,
});
const sandbox = {
  document: { getElementById: stubElement, hidden: false, createElement: stubElement,
              body: { appendChild() {} } },
  addEventListener() {},
  fetch: () => new Promise(() => {}),          // 시작 시 load() 가 여기서 멈춥니다
  location: { search: "", reload() {} },
  navigator: { clipboard: { writeText: async () => {} } },
  setTimeout, clearTimeout, console, URLSearchParams,
};
vm.createContext(sandbox);
// const 로 선언된 state 는 vm 전역 객체에 자동으로 붙지 않습니다.
// 같은 스코프에서 한 줄 덧붙여 꺼냅니다.
vm.runInContext(`${source}\n;globalThis.__probe = { state, plainText };`, sandbox);
const probe = sandbox.__probe;

const input = JSON.parse(fs.readFileSync(0, "utf8"));
probe.state.date = input.digest.date;
probe.state.data = {
  date: input.digest.date,
  generated_at: input.digest.generated_at,
  market: input.digest.market,
  analysis: input.digest.analysis,
  sectors: input.digest.sectors.map((s) => ({
    ...s,
    articles: input.digest.articles.filter((a) => a.sector === s.id),
  })),
};
probe.state.excluded = new Set(input.excluded || []);
process.stdout.write(probe.plainText());

// 날짜 선택 시트용 달력 줄 계산(테마·앱 의존 없이 순수 계산이라 node 테스트로 시험한다).

const pad = (n) => String(n).padStart(2, "0");

/**
 * 월요일부터 시작하는 달 달력. 그 달에 필요한 줄(4~6줄)만 만들고 앞뒤 빈 칸은 null 이다.
 * @param {number} year
 * @param {number} month 1~12
 * @returns {(string | null)[][]} 줄마다 7칸, 날짜는 "YYYY-MM-DD"
 */
export function monthWeeks(year, month) {
  const lead = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const days = new Date(year, month, 0).getDate();
  const cells = [
    ...Array.from({ length: lead }, () => null),
    ...Array.from({ length: days }, (_, i) => `${year}-${pad(month)}-${pad(i + 1)}`),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));
}

import { useRouter } from "expo-router";
import { StyleSheet, Text } from "react-native";

import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font } from "@/theme";

import EmptyBox from "../components/report/EmptyBox";
import EventList from "../components/report/EventList";
import InsightCard from "../components/report/InsightCard";
import NoFamilyBox from "../components/report/NoFamilyBox";
import NewsCard from "../components/report/NewsCard";
import NewspaperHeader from "../components/report/NewspaperHeader";
import NoticeBox from "../components/report/NoticeBox";
import RecordFold from "../components/report/RecordFold";
import ReportSkeleton from "../components/report/ReportSkeleton";
import StatBand from "../components/report/StatBand";
import { issueForWeek, recordDefaultOpen, recordSummary } from "../news/newsView";
import { useWeeklyNews } from "../news/useWeeklyNews";
import { useWeeklyReport } from "../report/useWeeklyReport";

/**
 * 마이 > 우리 가족 뉴스: 신문형 머리글, 메인 기사와 단신, 그리고 접을 수 있는 "한 주의 기록"(공유한 일정·할 일·문서를 규칙으로 모은 통계).
 * 뉴스가 읽힌 주는 기록을 접어 두고, 뉴스가 없는 주는 기록 요약을 펼쳐서 보여 준다.
 * @returns {import("react").ReactElement}
 */
export default function ReportScreen() {
  const router = useRouter();
  const r = useWeeklyReport();
  const { status, report, range } = r;
  const news = useWeeklyNews({ weekStart: range.start, enabled: status === "ready" });
  const openSchedule = () => router.push("/schedule");

  let body = null;
  if (status === "loading") {
    body = <ReportSkeleton />;
  } else if (status === "nofamily") {
    body = <NoFamilyBox onCreate={() => router.push("/family-create")} onJoin={() => router.push("/family-join")} />;
  } else if (status === "error") {
    body = <NoticeBox title="불러오지 못했어요" message={r.errorMessage} actionLabel="다시 시도" onAction={r.retry} />;
  } else if (report) {
    const noun = report.isCurrent ? "이번 주" : "그 주";
    const docsReloading = r.docsRetrying;
    // 문서를 못 불러왔거나 다시 불러오는 중이면 알림이 보이도록 기록 영역을 펼친다(뉴스가 있는 주에도)
    const docsProblem = r.docsStatus === "failed" || docsReloading ? "failed" : r.docsStatus;
    body = (
      <>
        <NewspaperHeader
          issue={issueForWeek(news.news, range.start)}
          range={range}
          canPrev={r.canPrev}
          canNext={r.canNext}
          onPrev={r.goPrev}
          onNext={r.goNext}
          onCurrent={r.goCurrent}
        />
        <NewsCard
          phase={news.phase}
          offset={range.offset}
          news={news.news}
          error={news.error}
          creating={news.creating}
          createError={news.createError}
          onCreate={news.create}
          onReload={news.reload}
          onOpenItem={(route) => router.push(route)}
        />
        <RecordFold
          key={range.start}
          summary={recordSummary(report, docsProblem)}
          defaultOpen={recordDefaultOpen({ phase: news.phase, news: news.news, weekStart: range.start, docsStatus: docsProblem })}
        >
          <StatBand
            sharedCount={report.sharedCount}
            todoDone={report.todoDone}
            todoTotal={report.todoTotal}
            docCount={report.docCount}
            docsStatus={r.docsStatus}
            isCurrent={report.isCurrent}
          />
          {r.docsStatus === "failed" || docsReloading ? (
            <NoticeBox
              title={docsReloading ? "문서를 다시 불러오는 중이에요" : "문서를 불러오지 못했어요"}
              message="일정과 할 일은 그대로 보여요. 문서만 다시 불러올 수 있어요."
              actionLabel={docsReloading ? "문서 다시 불러오는 중…" : "문서 다시 불러오기"}
              onAction={r.retryDocs}
              actionDisabled={docsReloading}
            />
          ) : null}
          {report.state === "all_empty" ? (
            <EmptyBox
              title={`${noun} 공유한 기록이 없어요`}
              description={`일정·할 일·문서를 공유하면 ${noun} 이야기가 여기에 모여요.`}
              actionLabel="일정 보러 가기"
              onAction={openSchedule}
            />
          ) : report.list.length > 0 ? (
            <EventList title={report.listTitle} total={report.listTotal} list={report.list} onPressItem={openSchedule} />
          ) : report.state === "events_empty" ? (
            <EmptyBox
              title={report.isCurrent ? "이번 주 공유 일정은 없어요" : "그 주에는 공유 일정이 없었어요"}
              description={report.isCurrent ? "일정을 공유하면 이번 주 이야기가 여기에 모여요." : "그 주에 공유된 일정이 없어요."}
              actionLabel={report.isCurrent ? "일정 보러 가기" : undefined}
              onAction={openSchedule}
            />
          ) : (
            <EmptyBox title={`${report.listTitle}이 없어요`} description="이번 주 공유 일정은 모두 지났어요." />
          )}
          {report.insights.length > 0 ? <InsightCard insights={report.insights} onOpenSchedule={openSchedule} /> : null}
        </RecordFold>
        <Text style={styles.footer}>
          가족에게 공유된 일정·할 일·문서를 기준으로 정리해요. 개인 일정과 채팅 원문은 사용하지 않아요.
        </Text>
      </>
    );
  }

  return (
    <Screen
      title="가족 뉴스"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      {body}
    </Screen>
  );
}

const styles = StyleSheet.create({
  footer: { ...font.caption, color: colors.textMuted },
});

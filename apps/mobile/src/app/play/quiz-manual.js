import QuizCreateScreen from "@/features/playground/screens/QuizCreateScreen";

/** 직접 내기로 바로 열리는 경로(OX/선택 전환은 화면 안에서 한다). */
export default function QuizManualRoute() {
  return <QuizCreateScreen initialMode="manual" />;
}

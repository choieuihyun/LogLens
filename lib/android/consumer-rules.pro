# LogLens 를 쓰는 앱에 자동 적용되는 R8/ProGuard 규칙입니다.
#
# 라이브러리 자체는 리플렉션을 쓰지 않아서 난독화·축소를 그대로 받아도 됩니다.
# 다만 한 가지 주의할 점이 있습니다.
#
# LogLens.e(domain, event, throwable) 로 예외를 넘기면 at= 필드에
# 스택 첫 프레임의 "클래스명.메서드명:줄번호" 가 들어갑니다.
# 릴리스 빌드에서 난독화가 걸려 있으면 이 값이 a.b:42 처럼 찍힙니다.
# 로그에서 그대로 읽고 싶다면 앱 쪽 proguard-rules.pro 에 아래를 넣으세요.
#
#   -keepattributes SourceFile,LineNumberTable
#   -renamesourcefileattribute SourceFile
#
# (그러면 매핑 파일로 복원할 수 있습니다. 뷰어의 retrace 는 아직 없습니다.)

# ── 릴리스 APK 에서 LogLens 호출 자체를 지우고 싶다면 ──────────────────────
#
# 라이브러리는 릴리스에서 기본으로 아무것도 내보내지 않습니다 (ReleasePolicy.SILENT).
# 하지만 그건 실행 중에 막는 것이라, 이벤트 이름과 메시지 문자열은 APK 안에 남습니다.
# 그것까지 없애려면 앱 쪽 proguard-rules.pro 에 아래를 넣어 빌드 단계에서 호출을 걷어냅니다.
#
#   -assumenosideeffects class io.loglens.core.LogLens {
#       public *** v(...);
#       public *** d(...);
#       public *** i(...);
#       public *** w(...);
#       public *** e(...);
#       public *** payload(...);
#   }
#
# static 을 적지 않아서 자바용(정적 메서드)과 Kotlin 의 "키" to 값 방식(LogLens.INSTANCE 의 메서드)이
# 함께 잡힙니다. init / install / addSink 는 넣지 않습니다 (지워도 동작에는 문제가 없지만 지울 이유가 없습니다).
#
# 이 규칙을 여기(라이브러리)에 넣어 모든 앱에 적용하지 않는 이유: 릴리스에서 경고·에러를 받으려고
# ReleasePolicy 를 연 앱의 로그까지 지워 버리기 때문입니다. 앱이 고를 일입니다.
#
# 넣은 뒤에는 릴리스 APK 의 dex 에서 이벤트 이름 문자열이 사라졌는지 직접 확인하세요.
# 인자를 만드는 코드(문자열 이어 붙이기, 배열 생성)는 최적화 설정에 따라 남을 수 있습니다.

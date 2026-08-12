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

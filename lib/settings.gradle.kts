// 라이브러리만 독립적으로 빌드한다. 뷰어(Python)는 gradle 과 무관하다.
//
// 주의: 이 파일들은 이 저장소가 만들어진 환경에서 **검증되지 않았다**
// (gradle / Android SDK 부재). core 모듈은 순수 자바라 `make test-lib` 로
// javac 만으로 컴파일·테스트된다. android 모듈은 소스만 있고 미컴파일 상태다.

rootProject.name = "loglens"

include(":core", ":android", ":sample-domains")

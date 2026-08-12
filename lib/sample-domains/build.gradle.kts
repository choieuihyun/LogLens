// sample-domains — 이 모듈은 **배포되지 않는다.**
//
// 도메인 목록은 각 프로젝트의 것이다. 여기 있는 AppDomain 은 복사해 가라고
// 놓아둔 예시일 뿐이다. 라이브러리가 도메인을 갖는 순간 재사용이 끝난다.

plugins {
    `java-library`
}

java {
    sourceCompatibility = JavaVersion.VERSION_1_8
    targetCompatibility = JavaVersion.VERSION_1_8
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

dependencies {
    api(project(":core"))
}

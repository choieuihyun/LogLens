// 라이브러리 빌드의 루트입니다. 여기서는 플러그인 버전만 정하고,
// 실제 설정은 각 모듈에 있습니다.
//
//   ./gradlew :android:assembleRelease   →  .aar 생성
//   ./gradlew test                       →  전체 테스트

plugins {
    id("com.android.library") version "8.7.3" apply false
    kotlin("jvm") version "2.0.21" apply false
    kotlin("android") version "2.0.21" apply false
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}

// 라이브러리 빌드는 lib/ 을 루트로 합니다. 뷰어(Python)와 문서까지
// gradle 이 훑을 이유가 없어서 저장소 루트와 분리했습니다.
//
//   ./gradlew :android:assembleRelease   →  배포용 .aar
//   ./gradlew test                       →  전체 테스트
//   ./gradlew :roundtrip:run             →  뷰어 파서와 대조할 로그 생성

pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "loglens"

// :core     순수 Kotlin/JVM. 안드로이드를 모릅니다. 테스트가 여기 붙습니다.
// :android  배포용 .aar. core 소스까지 함께 컴파일해 하나로 완결됩니다.
include(":core", ":android", ":sample-domains")

// 저장소 다른 곳에 있는 것들도 gradle 모듈로 끌어옵니다.
include(":roundtrip")
project(":roundtrip").projectDir = file("../tools/roundtrip")
include(":demo")
project(":demo").projectDir = file("../sample-app/jvm")

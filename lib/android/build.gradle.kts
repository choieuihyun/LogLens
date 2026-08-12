// android — logcat 싱크와 부트스트랩. 안드로이드에 의존하는 유일한 모듈.
//
// core 를 api 로 노출하므로 앱은 이 모듈 하나만 붙이면 된다:
//     implementation("io.loglens:loglens-android:0.1.0")
//
// 미검증: 이 저장소가 만들어진 환경에 Android SDK / AGP 가 없다.

plugins {
    id("com.android.library")
    `maven-publish`
}

android {
    namespace = "io.loglens.android"
    compileSdk = 34

    defaultConfig {
        minSdk = 21
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    publishing {
        singleVariant("release") { withSourcesJar() }
    }
}

dependencies {
    api(project(":core"))
}

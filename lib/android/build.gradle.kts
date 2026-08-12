// 배포용 .aar 을 만드는 모듈입니다.
//
//   ./gradlew :android:assembleRelease
//   → android/build/outputs/aar/loglens-release.aar
//
// 이 .aar 하나만 앱에 넣으면 됩니다. 외부 의존성이 없습니다.

plugins {
    id("com.android.library")
    kotlin("android")
    `maven-publish`
}

val libVersion = "0.1.0"

android {
    namespace = "io.loglens.android"
    compileSdk = 34

    defaultConfig {
        minSdk = 21
        consumerProguardFiles("consumer-rules.pro")
    }

    // core 는 순수 자바라 별도 모듈로 두고 JVM 에서 테스트하지만,
    // .aar 은 그것까지 담아서 하나로 완결되게 만듭니다.
    // project(":core") 로 의존하면 .aar 에 클래스가 안 들어가서
    // 앱이 core 를 따로 받아야 하는데, 그러면 "파일 하나 넣으면 끝"이 깨집니다.
    sourceSets {
        getByName("main") {
            java.srcDir("../core/src/main/kotlin")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    publishing {
        singleVariant("release") {
            withSourcesJar()
        }
    }
}

base {
    // 결과물 이름: loglens-release.aar  (기본값은 모듈명인 android-release.aar)
    archivesName.set("loglens")
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

publishing {
    publications {
        register<MavenPublication>("release") {
            groupId = "io.loglens"
            artifactId = "loglens"
            version = libVersion
            afterEvaluate { from(components["release"]) }
        }
    }
    repositories {
        // 사내 Nexus 나 JitPack 대신, 우선 로컬 파일 저장소로 뽑습니다.
        //   ./gradlew :android:publishReleasePublicationToLocalRepoRepository
        maven {
            name = "localRepo"
            url = uri("${rootProject.layout.buildDirectory.get()}/repo")
        }
    }
}

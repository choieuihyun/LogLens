// 순수 Kotlin/JVM. 안드로이드도, 외부 라이브러리도 모릅니다.
//
// 이게 의도한 선택입니다. 형식을 만드는 로직이 안드로이드에 묶여 있으면
// 일반 JVM 에서 테스트할 수 없고, 뷰어 파서와 대조하는 검증도 못 합니다.

plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
    compilerOptions {
        // 안드로이드 minSdk 21 을 지원하려면 바이트코드가 1.8 이어야 합니다.
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_1_8)
        freeCompilerArgs.add("-Xjvm-default=all")
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_1_8
    targetCompatibility = JavaVersion.VERSION_1_8
}

dependencies {
    // 배포물에는 들어가지 않습니다. 테스트에서만 씁니다.
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
}

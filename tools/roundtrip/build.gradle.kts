// 뷰어 파서와 대조할 로그를 만들어 내는 도구입니다.
//
//   ./gradlew :roundtrip:run --quiet | python3 tools/roundtrip/verify.py

plugins {
    kotlin("jvm")
    application
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(project(":core"))
}

application {
    mainClass.set("io.loglens.tools.RoundTripKt")
}

tasks.named<JavaExec>("run") {
    // 출력이 그대로 파이프로 넘어가야 합니다.
    standardOutput = System.out
}

// 기기 없이 진짜 라이브러리로 로그를 뿜는 데모입니다.
//
//   ./gradlew :demo:run --args="--out build/demo/app.log"
//
// Kotlin 호출부와 Java 호출부를 둘 다 담았습니다.
// 두 API 가 실제로 같이 동작하는지 여기서 확인됩니다.

plugins {
    kotlin("jvm")
    application
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(project(":core"))
    implementation(project(":sample-domains"))
}

application {
    mainClass.set("io.loglens.demo.DemoKt")
}

tasks.named<JavaExec>("run") {
    standardOutput = System.out
}

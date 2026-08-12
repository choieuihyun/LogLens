// core — 순수 자바. 안드로이드도, 서드파티도 모른다.
//
// 이게 의도적인 선택이다: 포맷터/정화기/마스커/절단기가 안드로이드에 묶여 있으면
// 계약의 핵심 로직을 일반 JVM 에서 테스트할 수 없고, 뷰어와의 왕복 검증도 못 한다.

plugins {
    `java-library`
    `maven-publish`
}

java {
    sourceCompatibility = JavaVersion.VERSION_1_8   // 낮은 minSdk 대응
    targetCompatibility = JavaVersion.VERSION_1_8
    withSourcesJar()
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

// 테스트는 JUnit 없이 도는 자체 하네스다 (CoreTests.main).
// 의존성 0 을 지키기 위한 선택. `make test-lib` 와 같은 것을 실행한다.
//
// 주의: src/test/java 는 **소스** 디렉터리라 그대로 classpath 에 넣으면 안 된다.
// 별도 SourceSet 으로 컴파일한 뒤 그 output 을 써야 한다. (gradle 미검증 구간)
val harness by sourceSets.creating {
    java.srcDir("src/test/java")
    compileClasspath += sourceSets["main"].output
    runtimeClasspath += sourceSets["main"].output
}

val coreTest by tasks.registering(JavaExec::class) {
    group = "verification"
    description = "core 단위 테스트 (JUnit 미사용)"
    classpath = harness.runtimeClasspath
    mainClass.set("io.loglens.core.CoreTests")
}

publishing {
    publications {
        create<MavenPublication>("maven") {
            groupId = "io.loglens"
            artifactId = "loglens-core"
            version = "0.1.0"
            from(components["java"])
        }
    }
}

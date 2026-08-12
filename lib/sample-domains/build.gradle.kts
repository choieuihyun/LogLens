// 이 모듈은 **배포되지 않습니다.**
//
// 도메인 목록은 각 프로젝트의 것입니다. 여기 있는 건 복사해 가라고 놓아둔 예시일 뿐입니다.
// 라이브러리가 도메인을 갖는 순간 재사용이 끝납니다.
//
// Kotlin 판과 Java 판을 둘 다 두었습니다. 자바가 대부분인 프로젝트도
// 그대로 복사해 쓸 수 있게 하기 위해서입니다.

plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_1_8)
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_1_8
    targetCompatibility = JavaVersion.VERSION_1_8
}

dependencies {
    api(project(":core"))
}

import groovy.json.JsonSlurper
import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}
val distribution = JsonSlurper().parse(rootProject.file("../../backend/src/omnicore/distribution.json")) as Map<*, *>
val releaseRequested = gradle.startParameter.taskNames.any {
    val task = it.substringAfterLast(':')
    task.contains("release", ignoreCase = true) || task in setOf("build", "assemble", "bundle")
}
val signingEnv = listOf("OMNICORE_ANDROID_KEYSTORE", "OMNICORE_ANDROID_STORE_PASSWORD",
    "OMNICORE_ANDROID_KEY_ALIAS", "OMNICORE_ANDROID_KEY_PASSWORD", "OMNICORE_ANDROID_RELEASE_ID",
    "OMNICORE_ANDROID_CERT_SHA256").associateWith { System.getenv(it).orEmpty() }
if (releaseRequested) {
    require(signingEnv.values.all { it.isNotBlank() }) { "Release signing requires all OMNICORE_ANDROID signing variables; no debug fallback." }
    require(File(signingEnv.getValue("OMNICORE_ANDROID_KEYSTORE")).isAbsolute) { "Keystore path must be absolute." }
    val keyFile = file(signingEnv.getValue("OMNICORE_ANDROID_KEYSTORE")).canonicalFile
    val projectRoot = rootProject.file("../..").canonicalFile.toPath()
    require(keyFile.isFile && !keyFile.toPath().startsWith(projectRoot)) { "Keystore must exist outside the repository." }
    require(signingEnv.getValue("OMNICORE_ANDROID_RELEASE_ID").matches(Regex("[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+"))) { "Invalid release application ID." }
    require(signingEnv.getValue("OMNICORE_ANDROID_CERT_SHA256").replace(":", "").matches(Regex("[a-fA-F0-9]{64}"))) { "A pinned release certificate SHA-256 is required." }
}

android {
    namespace = "io.github.vex2137.omnicore"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = if (releaseRequested) signingEnv.getValue("OMNICORE_ANDROID_RELEASE_ID") else distribution["android_application_id"] as String
        minSdk = 26
        targetSdk = 36
        versionCode = (distribution["android_version_code"] as Number).toInt()
        versionName = distribution["version"] as String
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        manifestPlaceholders["launcherLabel"] = "@string/launcher_name"
    }
    signingConfigs {
        if (releaseRequested) create("ownerRelease") {
            storeFile = file(signingEnv.getValue("OMNICORE_ANDROID_KEYSTORE"))
            storePassword = signingEnv.getValue("OMNICORE_ANDROID_STORE_PASSWORD")
            keyAlias = signingEnv.getValue("OMNICORE_ANDROID_KEY_ALIAS")
            keyPassword = signingEnv.getValue("OMNICORE_ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        getByName("release") {
            if (releaseRequested) signingConfig = signingConfigs.getByName("ownerRelease")
            manifestPlaceholders["launcherLabel"] = "@string/app_name"
        }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    splits { abi { isEnable = true; reset(); include("arm64-v8a", "x86_64"); isUniversalApk = false } }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    testOptions { animationsDisabled = true }
}
dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.04.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.1")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

// Explicit real-engine suite: never silently pass or skip inference without weights.
tasks.withType<Test>().configureEach {
    filter {
        if (providers.gradleProperty("realBackend").isPresent) includeTestsMatching("*.RealBackendTest")
        else excludeTestsMatching("*.RealBackendTest")
    }
}

import groovy.json.JsonSlurper

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}
val distribution = JsonSlurper().parse(rootProject.file("../../backend/src/omnicore/distribution.json")) as Map<*, *>

android {
    namespace = "io.github.vex2137.omnicore"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = distribution["android_application_id"] as String
        minSdk = 26
        targetSdk = 36
        versionCode = (distribution["android_version_code"] as Number).toInt()
        versionName = distribution["version"] as String
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    splits { abi { isEnable = true; reset(); include("arm64-v8a", "x86_64"); isUniversalApk = false } }
    val releaseKeystorePath = System.getenv("OMNICORE_KEYSTORE_PATH")?.takeIf { it.isNotBlank() }
    val releaseKeyAlias = System.getenv("OMNICORE_KEY_ALIAS")?.takeIf { it.isNotBlank() }
    val releaseKeystorePassword = System.getenv("OMNICORE_KEYSTORE_PASSWORD")
    val releaseKeyPassword = System.getenv("OMNICORE_KEY_PASSWORD")
    if (
        releaseKeystorePath != null &&
            releaseKeyAlias != null &&
            !releaseKeystorePassword.isNullOrEmpty() &&
            !releaseKeyPassword.isNullOrEmpty()
    ) {
        signingConfigs {
            create("release") {
                storeFile = file(releaseKeystorePath)
                storePassword = releaseKeystorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
        buildTypes {
            getByName("release") {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    packaging {
        jniLibs.useLegacyPackaging = true
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
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

val verifyNativeInferenceBinary by
    tasks.registering {
        doLast {
            val nativeLib = file("src/main/jniLibs/arm64-v8a/libomnicore_llama.so")
            if (!nativeLib.isFile || nativeLib.length() < 1_000_000L) {
                throw GradleException(
                    "Missing native Android inference binary at ${nativeLib.absolutePath}. " +
                        "Run: python3 scripts/build_android_native.py --sdk <ANDROID_SDK_ROOT>"
                )
            }
        }
    }

tasks.matching { it.name == "packageDebug" || it.name == "packageRelease" }.configureEach {
    dependsOn(verifyNativeInferenceBinary)
}

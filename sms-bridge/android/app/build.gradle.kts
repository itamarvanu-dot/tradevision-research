plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.itamar.smsbridge"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.itamar.smsbridge"
        minSdk = 26
        targetSdk = 34
        versionCode = 3
        versionName = "3.0"
    }

    buildTypes {
        release {
            // Signed with the debug key so the APK is installable straight from CI.
            // This app is sideloaded, never published to Play, and ships no secrets: it is
            // configured entirely by the enrollment link the controller sends.
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    // Only the push receiver. Firebase is configured at runtime from the enrollment link,
    // so there is no google-services.json baked into the APK.
    implementation(platform("com.google.firebase:firebase-bom:33.5.1"))
    implementation("com.google.firebase:firebase-messaging")

    testImplementation("junit:junit:4.13.2")
    // android.jar ships org.json as stubs; the real one lets the payload/parse code run in tests.
    testImplementation("org.json:json:20240303")
}

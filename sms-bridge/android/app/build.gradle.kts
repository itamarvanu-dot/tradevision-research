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
        versionCode = 2
        versionName = "2.0"

        // Where the iPhone page is hosted. The QR code points here; it can also be changed
        // from inside the app, so a different host never needs a rebuild.
        val pageUrl = (project.findProperty("smsbridge.pageUrl") as String?)
            ?: "https://itamarvanu-dot.github.io/tradevision-research/sms-bridge/web/"
        buildConfigField("String", "DEFAULT_PAGE_URL", "\"$pageUrl\"")
    }

    // The iPhone page ships inside the APK; setup publishes it to the project's Firebase Hosting.
    sourceSets["main"].assets.srcDir("../../web")

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            // Signed with the debug key so the APK is installable straight from CI.
            // This app is sideloaded, never published to Play.
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
    implementation("com.google.zxing:core:3.5.3")

    // Only the push receiver. Firebase is configured at runtime from the files the user
    // picks in the app, so there is no google-services.json baked into the APK.
    implementation(platform("com.google.firebase:firebase-bom:33.5.1"))
    implementation("com.google.firebase:firebase-messaging")

    testImplementation("junit:junit:4.13.2")
    // android.jar ships org.json as stubs; the real one lets the payload code run in unit tests.
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}

import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.itamar.smsbridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.itamar.smsbridge"
        minSdk = 26
        targetSdk = 36
        // 1-3 were the sideloaded APKs; Play builds start above them.
        versionCode = 10
        versionName = "4.0"
    }

    // Play upload key. Its location and passwords live OUTSIDE this public repo, in a
    // properties file passed as -PsmsbridgeSigning=<path> (or the SMSBRIDGE_SIGNING env var)
    // with keys storeFile, storePassword, keyAlias, keyPassword.
    // Without it (e.g. CI), release falls back to the debug key so assembleRelease still works.
    val signingPropsPath = (findProperty("smsbridgeSigning") as String?) ?: System.getenv("SMSBRIDGE_SIGNING")
    val uploadSigning = signingPropsPath?.let { path ->
        val props = Properties().apply { file(path).inputStream().use { load(it) } }
        signingConfigs.create("upload") {
            storeFile = file(props.getProperty("storeFile"))
            storePassword = props.getProperty("storePassword")
            keyAlias = props.getProperty("keyAlias")
            keyPassword = props.getProperty("keyPassword")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = uploadSigning ?: signingConfigs.getByName("debug")
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
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.1")

    // Only the push receiver. Firebase is configured at runtime from the enrollment link,
    // so there is no google-services.json baked into the APK.
    implementation(platform("com.google.firebase:firebase-bom:33.16.0"))
    implementation("com.google.firebase:firebase-messaging")

    testImplementation("junit:junit:4.13.2")
    // android.jar ships org.json as stubs; the real one lets the payload/parse code run in tests.
    testImplementation("org.json:json:20240303")
}

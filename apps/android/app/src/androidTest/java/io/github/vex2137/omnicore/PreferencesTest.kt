package io.github.vex2137.omnicore

import android.content.res.Resources
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PreferencesTest {
    @Test
    fun firstSystemLanguageIsPersistedAndManualChoiceSurvivesNewSettingsInstance() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = context.getSharedPreferences("omnicore", 0)
        val previous = prefs.getString("language", null)
        try {
            prefs.edit().remove("language").commit()
            val detected = SecureSettings(context).language
            assertEquals(
                initialLanguage(
                    Resources.getSystem().configuration.locales.toLanguageTags().split(',')
                ),
                detected,
            )
            assertEquals(detected, prefs.getString("language", null))
            SecureSettings(context).language = "pl-PL"
            assertEquals("pl-PL", SecureSettings(context).language)
            SecureSettings(context).language = "en-US"
            assertEquals("en-US", SecureSettings(context).language)
        } finally {
            prefs.edit().putString("language", previous).commit()
        }
    }
}

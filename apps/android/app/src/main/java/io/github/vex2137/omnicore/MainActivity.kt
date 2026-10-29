package io.github.vex2137.omnicore

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat

class MainActivity : AppCompatActivity() {
    private val viewModel: OmniViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        val locale = SecureSettings(this).language
        if (AppCompatDelegate.getApplicationLocales().toLanguageTags() != locale)
            AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(locale))
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            OmniCoreApp(viewModel) { language ->
                viewModel.setLanguage(language)
                AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(language))
            }
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.resume()
    }

    override fun onStop() {
        if (!isChangingConfigurations) viewModel.pause()
        super.onStop()
    }
}

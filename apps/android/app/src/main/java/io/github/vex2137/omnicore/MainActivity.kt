package io.github.vex2137.omnicore

import android.net.ConnectivityManager
import android.net.Network
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider

class MainActivity : AppCompatActivity() {
    private val viewModel: OmniViewModel by viewModels {
        object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T =
                OmniViewModel(SecureSettings(applicationContext)) as T
        }
    }
    private var currentNetwork: Network? = null
    private val networkCallback =
        object : ConnectivityManager.NetworkCallback() {
            override fun onLost(network: Network) {
                Handler(Looper.getMainLooper()).post { if (currentNetwork == network) { currentNetwork = null; viewModel.networkLost() } }
            }

            override fun onAvailable(network: Network) {
                Handler(Looper.getMainLooper()).post { currentNetwork = network; viewModel.networkAvailable() }
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        val locale = SecureSettings(this).language
        if (AppCompatDelegate.getApplicationLocales().toLanguageTags() != locale)
            AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(locale))
        super.onCreate(savedInstanceState)
        val connectivity = getSystemService(ConnectivityManager::class.java)
        connectivity.registerDefaultNetworkCallback(networkCallback)
        currentNetwork = connectivity.activeNetwork
        if (currentNetwork == null) viewModel.networkLost()
        enableEdgeToEdge()
        setContent {
            OmniCoreApp(viewModel) { language ->
                viewModel.setLanguage(language)
                AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(language))
            }
        }
    }

    override fun onDestroy() {
        getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(networkCallback)
        super.onDestroy()
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

"""
TFP UI Screen Stubs - Placeholder for Platform-Specific Implementation

These stubs define the interface contract for Flutter/React Native implementation.
Each stub documents:
- Required UI components
- User interactions
- Protocol adapter calls
- Accessibility requirements
"""

from dataclasses import dataclass


# ==================== 📡 DISCOVER SCREEN (Listen) ====================

@dataclass
class DiscoverScreenSpec:
    """
    📡 Listen Screen - Browse & Play Content

    User Flow:
    1. See grid of content cards (icon + title + duration)
    2. Tap card → Playback starts immediately
    3. Swipe categories horizontally
    4. Long-press → Pin option

    Components:
    - Category carousel (horizontal scroll)
    - Content grid (3 columns, large tap targets 48x48dp min)
    - Player bar (sticky bottom, shows current playback)
    - Voice search button (top-right)

    Accessibility:
    - Screen reader labels for all icons
    - High contrast mode support
    - Minimum font size 18sp
    - Haptic feedback on tap
    """

    required_widgets = [
        "CategoryCarousel",
        "ContentGrid",
        "PlayerBar",
        "VoiceSearchButton"
    ]

    protocol_calls = [
        "adapter.browse_content(category)",
        "adapter.play_content(content_id)",
        "adapter.pin_content(content_id)"
    ]

    user_metaphors = {
        "category": "Topic",
        "content_card": "Story",
        "play": "Listen",
        "pin": "Save for later"
    }


def discover_screen_stub():
    """
    Pseudo-code for Discover Screen implementation

    Flutter example:
    ```dart
    class DiscoverScreen extends StatelessWidget {
      final ProtocolAdapter adapter;

      @override
      Widget build(BuildContext context) {
        return Column(
          children: [
            CategoryCarousel(
              categories: ['emergency', 'news', 'education'],
              onTap: (cat) => adapter.browse_content(cat),
            ),
            Expanded(
              child: ContentGrid(
                items: await adapter.browse_content(),
                onTap: (item) => adapter.play_content(item.id),
                onLongPress: (item) => _showPinDialog(item),
              ),
            ),
            PlayerBar(
              currentItem: currentPlayer,
              onTap: () => _expandPlayer(),
            ),
          ],
        );
      }
    }
    ```
    """
    pass


# ==================== 📤 SHARE SCREEN ====================

@dataclass
class ShareScreenSpec:
    """
    📤 Share Screen - Record & Publish

    User Flow:
    1. Tap microphone/camera icon
    2. Record voice or take photo
    3. Add optional title (voice-to-text)
    4. Select category (icon grid)
    5. Tap "Send to Network"
    6. See confirmation: "Shared to X neighbors. Earned Y thanks!"

    Components:
    - Record button (large, centered)
    - Media preview thumbnail
    - Category selector (icon grid)
    - Title input (optional, voice-first)
    - Send button

    Accessibility:
    - Voice guidance throughout
    - Large record button (min 72x72dp)
    - Visual recording indicator (pulsing ring)
    - Auto-captions for voice input
    """

    required_widgets = [
        "RecordButton",
        "MediaPreview",
        "CategorySelector",
        "TitleInput",
        "SendButton"
    ]

    protocol_calls = [
        "adapter.record_and_share(media_type, media_data, title, category)"
    ]

    user_metaphors = {
        "record": "Tell your story",
        "category": "What's this about?",
        "send": "Share with neighbors"
    }


def share_screen_stub():
    """
    Pseudo-code for Share Screen implementation

    React Native example:
    ```jsx
    function ShareScreen({ adapter }) {
      const [recording, setRecording] = useState(false);
      const [mediaData, setMediaData] = useState(null);

      const handleRecord = async () => {
        setRecording(true);
        const audio = await AudioRecorder.start();
        setRecording(false);
        setMediaData(audio);
      };

      const handleSend = async () => {
        const thanks = await adapter.record_and_share(
          'voice',
          mediaData,
          title,
          category
        );
        showToast(`Shared to 12 neighbors. Earned ${thanks} thanks!`);
      };

      return (
        <View>
          <RecordButton
            onPress={handleRecord}
            isRecording={recording}
          />
          {mediaData && <MediaPreview data={mediaData} />}
          <CategorySelector onSelect={setCategory} />
          <SendButton onPress={handleSend} />
        </View>
      );
    }
    ```
    """
    pass


# ==================== 🔄 EARN SCREEN ====================

@dataclass
class EarnScreenSpec:
    """
    🔄 Earn Screen - Toggle Charge Mode

    User Flow:
    1. See big toggle switch
    2. Read explanation: "Help neighbors while charging"
    3. Toggle ON when device is charging
    4. See live metrics: "Helping X neighbors", "Y thanks earned today"
    5. Toggle OFF anytime

    Safety Indicators:
    - Battery level warning (<30%)
    - Temperature warning (>45°C)
    - Auto-pause if device gets hot

    Components:
    - Large toggle switch (centered)
    - Explanation text + illustration
    - Live metrics dashboard
    - Safety status indicators
    - History graph (optional)

    Accessibility:
    - Voice explanation of earn mode
    - High contrast toggle state
    - Haptic feedback on toggle
    - Simple language (grade 5 reading level)
    """

    required_widgets = [
        "EarnToggle",
        "ExplanationCard",
        "MetricsDashboard",
        "SafetyIndicators"
    ]

    protocol_calls = [
        "adapter.toggle_earn_mode(enabled)",
        "adapter.get_thanks_summary()"
    ]

    user_metaphors = {
        "toggle": "Help while charging",
        "thanks": "Thanks from neighbors",
        "metrics": "Your contribution"
    }


def earn_screen_stub():
    """
    Pseudo-code for Earn Screen implementation

    Flutter example:
    ```dart
    class EarnScreen extends StatefulWidget {
      @override
      _EarnScreenState createState() => _EarnScreenState();
    }

    class _EarnScreenState extends State<EarnScreen> {
      bool earnEnabled = false;
      ThanksSummary? summary;

      Future<void> toggleEarn(bool enabled) async {
        setState(() => earnEnabled = enabled);
        summary = await adapter.toggle_earn_mode(enabled);

        if (enabled) {
          showSnackbar('Helping neighbors while charging!');
        }
      }

      @override
      Widget build(BuildContext context) {
        return Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text('Help neighbors while charging'),
            ToggleSwitch(
              value: earnEnabled,
              onChanged: toggleEarn,
              size: Size(100, 50), // Extra large
            ),
            if (summary) ...[
              MetricCard('Thanks earned', summary.total_thanks),
              MetricCard('Neighbors helped', summary.neighbors_helped),
            ],
          ],
        );
      }
    }
    ```
    """
    pass


# ==================== ONBOARDING SCREEN ====================

@dataclass
class OnboardingScreenSpec:
    """
    Onboarding - 30-Second Voice-Guided Flow

    User Flow:
    1. App launches → No login required
    2. Voice greeting in local language
    3. Three buttons appear one by one with voice explanation
    4. User taps each button to try it
    5. Done → Main app ready

    Voice Script (English example):
    - "Welcome! This is your community radio."
    - "Tap here to listen to stories from nearby." (📡)
    - "Tap here to record your voice or photo." (📤)
    - "Tap here while charging to help neighbors." (🔄)
    - "You're ready! Explore freely."

    Components:
    - Full-screen illustrations (one per step)
    - Large animated buttons
    - Voice audio player (auto-play)
    - Skip button (top-right, small)
    - Language selector (first screen only)

    Accessibility:
    - 50+ language packs included
    - Voice-first (text is secondary)
    - No reading required
    - Progress indicator (dots)
    """

    required_widgets = [
        "IllustrationCarousel",
        "VoicePlayer",
        "InteractiveButtons",
        "LanguageSelector",
        "SkipButton"
    ]

    protocol_calls = [
        "adapter.initialize()",
        "adapter.get_network_status()"
    ]

    supported_languages = [
        "en", "es", "fr", "ar", "hi", "bn", "pt", "id",
        "ur", "zh", "ru", "ja", "sw", "de", "ko", "vi",
        # ... 50+ total
    ]


def onboarding_screen_stub():
    """
    Pseudo-code for Onboarding Screen implementation

    Key requirement: Zero text reading necessary.
    All instructions via voice + iconography.

    Flutter example:
    ```dart
    class OnboardingScreen extends StatefulWidget {
      @override
      _OnboardingScreenState createState() => _OnboardingScreenState();
    }

    class _OnboardingScreenState extends State<OnboardingScreen> {
      int currentStep = 0;
      String selectedLanguage = 'auto';

      final steps = [
        OnboardingStep(
          voiceFile: 'welcome_{lang}.mp3',
          illustration: 'illustration_welcome.png',
          buttonText: 'Get Started',
          buttonIcon: 'icon_checkmark',
        ),
        OnboardingStep(
          voiceFile: 'listen_tutorial_{lang}.mp3',
          illustration: 'illustration_listen.png',
          buttonText: 'Try Listen',
          buttonIcon: 'icon_speaker',
          action: () => adapter.browse_content(),
        ),
        // ... more steps
      ];

      void playVoice() {
        final voicePath = steps[currentStep].voiceFile
          .replaceAll('{lang}', selectedLanguage);
        AudioPlayer.play(voicePath);
      }

      @override
      Widget build(BuildContext context) {
        return Stack(
          children: [
            Illustration(image: steps[currentStep].illustration),
            VoiceButton(onTap: playVoice),
            ActionButton(
              text: steps[currentStep].buttonText,
              icon: steps[currentStep].buttonIcon,
              onTap: () {
                steps[currentStep].action?.call();
                setState(() => currentStep++);
              },
            ),
          ],
        );
      }
    }
    ```
    """
    pass


# ==================== ICON GUIDELINES ====================

UNIVERSAL_ICONS = {
    # Core Actions
    'icon_listen': 'Ear/speaker symbol, no text',
    'icon_share': 'Microphone + camera crossed, no text',
    'icon_earn': 'Battery + handshake, no text',
    'icon_play': 'Universal play triangle',
    'icon_pause': 'Two vertical bars',

    # Categories
    'icon_emergency': 'Warning triangle with exclamation',
    'icon_news': 'Newspaper or broadcast waves',
    'icon_education': 'Open book or graduation cap',
    'icon_entertainment': 'Music note + film strip',
    'icon_community': 'Group of people silhouettes',

    # Status
    'icon_downloading': 'Downward arrow with dots',
    'icon_cached': 'Checkmark inside circle',
    'icon_neighbors': 'Multiple person icons',
    'icon_thanks': 'Heart or thumbs-up',

    # Navigation
    'icon_back': 'Left arrow',
    'icon_close': 'X mark',
    'icon_settings': 'Gear (hidden, advanced only)',
    'icon_language': 'Speech bubble with globe',
}

ICON_SPECIFICATIONS = {
    'size_min_dp': 48,
    'size_recommended_dp': 64,
    'stroke_width_dp': 3,
    'color_primary': '#1a1a1a',  # High contrast dark
    'color_secondary': '#f5f5f5',  # High contrast light
    'color_accent': '#007aff',  # Blue for actions
    'style': 'Filled, not outlined (better visibility)',
    'text': 'Never include text in icons',
}


# ==================== VOICE GUIDE SPECIFICATIONS ====================

VOICE_GUIDE_SPECS = {
    'format': 'MP3, 128kbps, mono',
    'duration_per_clip': '< 10 seconds',
    'total_onboarding': '< 30 seconds',
    'languages': 50,
    'voice_type': 'Warm, friendly, local accent',
    'pace': 'Slow, clear enunciation',
    'background': 'Silent (no music)',

    'required_clips': [
        'welcome_{lang}.mp3',
        'listen_instruction_{lang}.mp3',
        'share_instruction_{lang}.mp3',
        'earn_instruction_{lang}.mp3',
        'onboarding_complete_{lang}.mp3',
        'error_generic_{lang}.mp3',
        'offline_message_{lang}.mp3',
    ]
}


if __name__ == "__main__":
    print("TFP UI Screen Stubs")
    print("=" * 50)
    print("\nThis file defines the contract for platform-specific UI implementation.")
    print("\nNext steps:")
    print("1. Choose platform (Flutter recommended)")
    print("2. Implement screens using these specs")
    print("3. Create universal icon set (SVG/PNG)")
    print("4. Record voice guides for 50+ languages")
    print("5. Test with target demographic (low-literacy users)")

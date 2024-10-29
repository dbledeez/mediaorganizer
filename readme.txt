Media Organizer Instructions
Prerequisites:
1. MediaInfo Application:
   * Download and install MediaInfo from the official website:
      * Windows: https://mediaarea.net/en/MediaInfo/Download/Windows
2. Microsoft Visual C++ Redistributable (Windows Only):
   * If prompted, install the required Microsoft Visual C++ Redistributable packages.
Usage:
1. Place the Executable and config.ini Together:
   * Ensure that the media_organizer.exe and the config.ini file are in the same directory.
2. Run the Executable:
   * Double-click the executable to launch the Media Organizer application.
   * If you have issues it is suggested to run application as administrator 
3. Configure Settings:
   * Edit the config.ini file to include your Sonarr API key and URL if you intend to use Sonarr integration.
4. Use the Application:
      1. Select Media Type: Choose either "Movies" or "TV Shows" from the dropdown menu.
      2. Select Folders: Click "Select Folders" to choose the folders you want to organize or analyze.
         1. The selected folders will appear in the listbox below.
         2. Use "Remove Selected Folder" to remove any unwanted selections.
      3. Start Organizing: Click "Start Organizing" to begin the process.
         1. A progress bar will indicate the script's progress.
         2. Detailed logs will appear in the text area with a black background and green text.
      4. Analyze Missing Episodes: Click "Missing Episodes" to start the analysis and interact with Sonarr.
         1. You'll be prompted to select missing episodes to add to Sonarr.
   * Monitoring and Logs
      1. The log output provides detailed information about the script's operations.
      2. Logs are also saved to media_organizer.log in the same directory as the script.
      3. If you encounter any errors, check this log file for detailed information.
Sonarr Integration
* Obtaining Sonarr API Key
   * In Sonarr, navigate to Settings > General.
   * Under the Security section, you'll find your API key.
   * Copy this key and paste it into the config.ini file under sonarr_api_key.
* Using Sonarr Features
   * The script can analyze missing episodes and interact with Sonarr to add them.
   * Ensure that the Sonarr URL and API key are correctly set in the config.ini file.
Additional Notes
* Testing
   * It's recommended to test the script with a small set of files before running it on your entire collection.
* Error Handling
   * The script includes comprehensive error handling to catch and log exceptions.
   * If issues arise, refer to the media_organizer.log file for troubleshooting.
* Performance
   * The speed of scanning and moving files depends on your system's hardware and the size of your media library.
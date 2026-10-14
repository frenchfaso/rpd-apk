#include <QApplication>
#include <QStyle>
#include <fstream>
#include <iostream>
#include <string>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    if (app.style()->objectName() != QStringLiteral("qt6gtk2")) {
        std::cerr << "Qt6 did not select the GTK2 style: "
                  << app.style()->objectName().toStdString() << '\n';
        return 1;
    }
    bool platform_theme = false;
    bool style = false;
    std::ifstream maps("/proc/self/maps");
    std::string line;
    while (std::getline(maps, line)) {
        platform_theme |= line.find("/platformthemes/libqt6gtk2.so") != std::string::npos;
        style |= line.find("/styles/libqt6gtk2-style.so") != std::string::npos;
    }
    if (!platform_theme || !style) {
        std::cerr << "Qt6 GTK2 platform-theme/style plugins are not both loaded\n";
        return 1;
    }
    std::cout << "Qt6 GTK2 platform-theme and style loaded\n";
    return 0;
}
